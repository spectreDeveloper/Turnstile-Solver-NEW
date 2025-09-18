import os
import sys
import time
import uuid
import random
import logging
import asyncio
from typing import Optional
import argparse
from quart import Quart, request, jsonify
import undetected_chromedriver as uc
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.service import Service
from db_results import init_db, save_result, load_result, cleanup_old_results
from browser_configs import browser_config
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.align import Align
from rich import box
from ipaddress import IPv6Network, IPv6Address



COLORS = {
    'MAGENTA': '\033[35m',
    'BLUE': '\033[34m',
    'GREEN': '\033[32m',
    'YELLOW': '\033[33m',
    'RED': '\033[31m',
    'RESET': '\033[0m',
}

# IPv6 subnets configuration - can be overridden via environment variable
import os

def validate_ipv6_subnets(subnets: list) -> list:
    """Validate IPv6 subnets format and return valid ones."""
    valid_subnets = []
    for subnet in subnets:
        subnet = subnet.strip()
        if not subnet:
            continue
        try:
            # Try to create IPv6Network to validate format
            IPv6Network(subnet, strict=False)
            valid_subnets.append(subnet)
        except ValueError as e:
            logger.warning(f"Invalid IPv6 subnet format: {subnet} - {e}")
    return valid_subnets

# Get and validate IPv6 subnets from environment
ipv6_subnets_env = os.getenv('IPV6_SUBNETS')
logger = logging.getLogger("TurnstileAPIServer")

if not ipv6_subnets_env:
    logger.warning("No IPv6 subnets configured. Please check the IPV6_SUBNETS environment variable.")
    sys.exit(1)

logger.info(f"Configured IPv6 subnets: {ipv6_subnets_env}, from now we will use random IPv6 addresses from these subnets each time we need to resolve a challenge.")

SUBNETS_IPV6 = validate_ipv6_subnets(ipv6_subnets_env.split(','))

def generate_ipv6_address() -> str:
    if not SUBNETS_IPV6:
        raise ValueError("No valid IPv6 subnets available. Please check IPV6_SUBNETS environment variable.")
    
    selected_subnet = random.choice(SUBNETS_IPV6)
    network = IPv6Network(selected_subnet, strict=False)
    host_bits = network.max_prefixlen - network.prefixlen
    random_address_int = random.getrandbits(host_bits)
    random_address_int %= 2**host_bits
    address = IPv6Address(network.network_address + random_address_int)
    return str(address)


class CustomLogger(logging.Logger):
    @staticmethod
    def format_message(level, color, message):
        timestamp = time.strftime('%H:%M:%S')
        return f"[{timestamp}] [{COLORS.get(color)}{level}{COLORS.get('RESET')}] -> {message}"

    def debug(self, message, *args, **kwargs):
        super().debug(self.format_message('DEBUG', 'MAGENTA', message), *args, **kwargs)

    def info(self, message, *args, **kwargs):
        super().info(self.format_message('INFO', 'BLUE', message), *args, **kwargs)

    def success(self, message, *args, **kwargs):
        super().info(self.format_message('SUCCESS', 'GREEN', message), *args, **kwargs)

    def warning(self, message, *args, **kwargs):
        super().warning(self.format_message('WARNING', 'YELLOW', message), *args, **kwargs)

    def error(self, message, *args, **kwargs):
        super().error(self.format_message('ERROR', 'RED', message), *args, **kwargs)


logging.setLoggerClass(CustomLogger)

# Create logger with proper initialization
logger = logging.getLogger("TurnstileAPIServer")
logger.setLevel(logging.DEBUG)

# Remove any existing handlers to avoid duplicates
for handler in logger.handlers[:]:
    logger.removeHandler(handler)

# Add new handler
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
logger.addHandler(handler)

# Ensure logger is properly configured
logger.propagate = False

def safe_log_success(message, *args, **kwargs):
    """Safely log success message with fallback to info if success method not available."""
    if hasattr(logger, 'success'):
        logger.success(message, *args, **kwargs)
    else:
        logger.info(f"[SUCCESS] {message}", *args, **kwargs)


class TurnstileAPIServer:

    def __init__(self, headless: bool, useragent: Optional[str], debug: bool, browser_type: str, thread: int, proxy_support: bool, ipv6_support: bool = False, use_random_config: bool = False, browser_name: Optional[str] = None, browser_version: Optional[str] = None):
        self.app = Quart(__name__)
        self.debug = debug
        self.browser_type = browser_type
        self.headless = headless
        self.thread_count = thread
        self.proxy_support = proxy_support
        self.ipv6_support = ipv6_support
        self.browser_pool = asyncio.Queue()
        self.use_random_config = use_random_config
        self.browser_name = browser_name
        self.browser_version = browser_version
        self.console = Console()
        
        # Validate IPv6 configuration
        if self.ipv6_support and not SUBNETS_IPV6:
            raise ValueError("IPv6 support is enabled but no valid IPv6 subnets are configured. Please check the IPV6_SUBNETS environment variable.")
        
        # Validate IPv6 and proxy conflict
        if self.ipv6_support and self.proxy_support:
            raise ValueError("IPv6 and proxy support cannot be enabled simultaneously. Please choose only one mode.")
        
        # Log IPv6 status
        if self.ipv6_support and SUBNETS_IPV6:
            logger.info(f"IPv6 support enabled with {len(SUBNETS_IPV6)} subnet(s): {', '.join(SUBNETS_IPV6)}")
        elif self.ipv6_support and not SUBNETS_IPV6:
            logger.warning("IPv6 support enabled but no valid subnets found")
        
        # Initialize useragent and sec_ch_ua attributes
        self.useragent = useragent
        self.sec_ch_ua = None
        
        
        if self.browser_type in ['chromium', 'chrome', 'msedge']:
            if browser_name and browser_version:
                config = browser_config.get_browser_config(browser_name, browser_version)
                if config:
                    useragent, sec_ch_ua = config
                    self.useragent = useragent
                    self.sec_ch_ua = sec_ch_ua
            elif useragent:
                self.useragent = useragent
            else:
                browser, version, useragent, sec_ch_ua = browser_config.get_random_browser_config(self.browser_type)
                self.browser_name = browser
                self.browser_version = version
                self.useragent = useragent
                self.sec_ch_ua = sec_ch_ua
        
        self.browser_args = []
        if self.useragent:
            self.browser_args.append(f"--user-agent={self.useragent}")

        self._setup_routes()

    def display_welcome(self):
        """Displays welcome screen with logo."""
        self.console.clear()
        
        combined_text = Text()
        combined_text.append("\n📢 Channel: ", style="bold white")
        combined_text.append("https://t.me/D3_vin", style="cyan")
        combined_text.append("\n💬 Chat: ", style="bold white")
        combined_text.append("https://t.me/D3vin_chat", style="cyan")
        combined_text.append("\n📁 GitHub: ", style="bold white")
        combined_text.append("https://github.com/D3-vin", style="cyan")
        combined_text.append("\n📁 Version: ", style="bold white")
        combined_text.append("1.2a", style="green")
        combined_text.append("\n")

        info_panel = Panel(
            Align.left(combined_text),
            title="[bold blue]Turnstile Solver[/bold blue]",
            subtitle="[bold magenta]Dev by D3vin[/bold magenta]",
            box=box.ROUNDED,
            border_style="bright_blue",
            padding=(0, 1),
            width=50
        )

        self.console.print(info_panel)
        self.console.print()




    def _setup_routes(self) -> None:
        """Set up the application routes."""
        self.app.before_serving(self._startup)
        self.app.route('/turnstile', methods=['GET'])(self.process_turnstile)
        self.app.route('/result', methods=['GET'])(self.get_result)
        self.app.route('/')(self.index)
        

    async def _startup(self) -> None:
        """Initialize the browser and page pool on startup."""
        self.display_welcome()
        logger.info("Starting browser initialization")
        try:
            await init_db()
            await self._initialize_browser()
            
            # Запускаем периодическую очистку старых результатов
            loop = asyncio.get_event_loop()
            loop.create_task(self._periodic_cleanup())
            
        except Exception as e:
            logger.error(f"Failed to initialize browser: {str(e)}")
            raise

    async def _initialize_browser(self) -> None:
        """Initialize the browser and create the page pool."""

        browser_configs = []
        for _ in range(self.thread_count):
            if self.use_random_config:
                browser, version, useragent, sec_ch_ua = browser_config.get_random_browser_config(self.browser_type)
            elif self.browser_name and self.browser_version:
                config = browser_config.get_browser_config(self.browser_name, self.browser_version)
                if config:
                    useragent, sec_ch_ua = config
                    browser = self.browser_name
                    version = self.browser_version
                else:
                    browser, version, useragent, sec_ch_ua = browser_config.get_random_browser_config(self.browser_type)
            else:
                browser = getattr(self, 'browser_name', 'custom')
                version = getattr(self, 'browser_version', 'custom')
                useragent = self.useragent
                sec_ch_ua = getattr(self, 'sec_ch_ua', '')


            browser_configs.append({
                'browser_name': browser,
                'browser_version': version,
                'useragent': useragent,
                'sec_ch_ua': sec_ch_ua
            })

        for i in range(self.thread_count):
            config = browser_configs[i]

            chrome_options = uc.ChromeOptions()
            chrome_options.add_argument("--window-position=0,0")
            chrome_options.add_argument("--force-device-scale-factor=1")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)

            # Docker compatibility arguments
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--disable-plugins")
            chrome_options.add_argument("--disable-images")
            chrome_options.add_argument("--disable-web-security")
            chrome_options.add_argument("--ignore-certificate-errors")
            chrome_options.add_argument("--ignore-ssl-errors")
            chrome_options.add_argument("--ignore-certificate-errors-spki-list")
            chrome_options.add_argument("--disable-background-timer-throttling")
            chrome_options.add_argument("--disable-renderer-backgrounding")
            chrome_options.add_argument("--disable-backgrounding-occluded-windows")

            if self.headless:
                chrome_options.add_argument("--headless=new")

            if config['useragent']:
                chrome_options.add_argument(f"--user-agent={config['useragent']}")

            # Add IPv6 arguments if IPv6 is enabled
            if self.ipv6_support and SUBNETS_IPV6:
                chrome_options.add_argument("--enable-ipv6")
                chrome_options.add_argument("--dns-prefetch-disable")
                chrome_options.add_argument("--host-resolver-rules=MAP * 0.0.0.0,EXCLUDE localhost")
                # Force IPv6 preference
                chrome_options.add_argument("--force-ipv6")
                if self.debug:
                    logger.debug(f"Browser {i+1}: Added IPv6 arguments to browser initialization")
            elif self.ipv6_support and not SUBNETS_IPV6:
                if self.debug:
                    logger.warning(f"Browser {i+1}: IPv6 enabled but no valid subnets - browser will use regular IP")

            browser = None
            try:
                # Try different configurations for better Docker compatibility
                try:
                    # First attempt: Standard undetected chrome
                    browser = uc.Chrome(options=chrome_options, version_main=None)
                except Exception as e1:
                    logger.debug(f"Browser {i+1}: First Chrome attempt failed: {e1}")
                    try:
                        # Second attempt: With explicit paths disabled
                        browser = uc.Chrome(
                            options=chrome_options,
                            driver_executable_path=None,
                            browser_executable_path=None,
                            version_main=None
                        )
                    except Exception as e2:
                        logger.debug(f"Browser {i+1}: Second Chrome attempt failed: {e2}")
                        try:
                            # Third attempt: Minimal configuration
                            browser = uc.Chrome(options=chrome_options)
                        except Exception as e3:
                            logger.debug(f"Browser {i+1}: Third Chrome attempt failed: {e3}")
                            try:
                                # Final fallback: Regular Selenium WebDriver
                                logger.info(f"Browser {i+1}: Falling back to regular Selenium WebDriver")
                                browser = webdriver.Chrome(options=chrome_options)
                            except Exception as e4:
                                logger.error(f"Browser {i+1}: All Chrome attempts failed (including fallback): {e4}")
                                browser = None

                if browser:
                    # Execute script to remove webdriver property
                    try:
                        browser.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

                        # Add chrome runtime
                        browser.execute_script("""
                            window.chrome = {
                                runtime: {},
                                loadTimes: function() {},
                                csi: function() {},
                            };
                        """)
                    except Exception as e:
                        logger.warning(f"Browser {i+1}: Failed to execute anti-detection scripts: {e}")

            except Exception as e:
                logger.error(f"Browser {i+1}: Critical Chrome driver initialization failure: {e}")
                browser = None

            if browser:
                await self.browser_pool.put((i+1, browser, config))
                if self.debug:
                    logger.info(f"Browser {i + 1} initialized successfully with {config['browser_name']} {config['browser_version']}")
            else:
                logger.warning(f"Browser {i + 1} failed to initialize - skipping")

        logger.info(f"Browser pool initialized with {self.browser_pool.qsize()} browsers")

        if self.use_random_config:
            logger.info(f"Each browser in pool received random configuration")
        elif self.browser_name and self.browser_version:
            logger.info(f"All browsers using configuration: {self.browser_name} {self.browser_version}")
        else:
            logger.info("Using custom configuration")

        if self.debug:
            for i, config in enumerate(browser_configs):
                logger.debug(f"Browser {i+1} config: {config['browser_name']} {config['browser_version']}")
                logger.debug(f"Browser {i+1} User-Agent: {config['useragent']}")
                logger.debug(f"Browser {i+1} Sec-CH-UA: {config['sec_ch_ua']}")

    async def _periodic_cleanup(self):
        """Periodic cleanup of old results every hour"""
        while True:
            try:
                await asyncio.sleep(3600)
                deleted_count = await cleanup_old_results(days_old=7)
                if deleted_count > 0:
                    logger.info(f"Cleaned up {deleted_count} old results")
            except Exception as e:
                logger.error(f"Error during periodic cleanup: {e}")


    async def _test_browser_ip(self, driver, index: int):
        """Test the browser's public IP address using ipify.org"""
        try:
            if self.debug:
                logger.debug(f"Browser {index}: Testing public IP address...")

            # Run in thread to avoid blocking
            def test_ip():
                try:
                    # Navigate to ipify.org to get the public IP
                    driver.get("https://api.ipify.org?format=json")

                    # Extract the IP from the page content
                    content = driver.find_element(By.TAG_NAME, "body").text

                    # Try to parse JSON response
                    import json
                    ip_data = json.loads(content.strip())
                    ip_address = ip_data.get("ip", "unknown")

                    # Determine if it's IPv4 or IPv6
                    if ":" in ip_address:
                        ip_type = "IPv6"
                        color = COLORS.get('GREEN')
                    else:
                        ip_type = "IPv4"
                        color = COLORS.get('BLUE')

                    logger.info(f"Browser {index}: Public IP - {color}{ip_address}{COLORS.get('RESET')} ({ip_type})")

                    if self.ipv6_support and ip_type == "IPv4":
                        logger.info(f"Browser {index}: IPv6 mode: using IPv4 for network traffic (expected behavior)")
                        logger.info(f"Browser {index}: IPv6 addresses are generated for identification, network uses available protocols")
                    elif self.ipv6_support and ip_type == "IPv6":
                        logger.info(f"Browser {index}: IPv6 mode: successfully using IPv6 for network traffic")

                except Exception as e:
                    logger.warning(f"Browser {index}: Failed to test IP: {e}")

            # Run in background thread
            await asyncio.get_event_loop().run_in_executor(None, test_ip)

        except Exception as e:
            logger.warning(f"Browser {index}: Failed to test public IP: {e}")

    async def _find_turnstile_elements(self, driver, index: int):
        """Selenium-based element finding"""
        def find_elements():
            selectors = [
                (By.CSS_SELECTOR, '.cf-turnstile'),
                (By.CSS_SELECTOR, '[data-sitekey]'),
                (By.CSS_SELECTOR, 'iframe[src*="turnstile"]'),
                (By.CSS_SELECTOR, 'iframe[title*="widget"]'),
                (By.CSS_SELECTOR, 'div[id*="turnstile"]'),
                (By.CSS_SELECTOR, 'div[class*="turnstile"]')
            ]

            elements = []
            for by, selector in selectors:
                try:
                    found_elements = driver.find_elements(by, selector)
                    count = len(found_elements)

                    if count > 0:
                        elements.append((selector, count))
                        if self.debug:
                            logger.debug(f"Browser {index}: Found {count} elements with selector '{selector}'")
                except Exception as e:
                    if self.debug:
                        logger.debug(f"Browser {index}: Selector '{selector}' failed: {str(e)}")
                    continue

            return elements

        return await asyncio.get_event_loop().run_in_executor(None, find_elements)

    async def _find_and_click_checkbox(self, driver, index: int):
        """Selenium-based iframe and checkbox handling"""
        def click_checkbox():
            try:
                # Пробуем разные селекторы iframe
                iframe_selectors = [
                    'iframe[src*="challenges.cloudflare.com"]',
                    'iframe[src*="turnstile"]',
                    'iframe[title*="widget"]'
                ]

                iframe_element = None
                for selector in iframe_selectors:
                    try:
                        iframes = driver.find_elements(By.CSS_SELECTOR, selector)
                        if iframes:
                            iframe_element = iframes[0]
                            if self.debug:
                                logger.debug(f"Browser {index}: Found Turnstile iframe with selector: {selector}")
                            break
                    except Exception as e:
                        if self.debug:
                            logger.debug(f"Browser {index}: Iframe selector '{selector}' failed: {str(e)}")
                        continue

                if iframe_element:
                    try:
                        # Switch to iframe
                        driver.switch_to.frame(iframe_element)

                        # Ищем чекбокс внутри iframe
                        checkbox_selectors = [
                            'input[type="checkbox"]',
                            '.cb-lb input[type="checkbox"]',
                            'label input[type="checkbox"]'
                        ]

                        for selector in checkbox_selectors:
                            try:
                                checkboxes = driver.find_elements(By.CSS_SELECTOR, selector)
                                if checkboxes:
                                    checkbox = checkboxes[0]
                                    ActionChains(driver).click(checkbox).perform()
                                    if self.debug:
                                        logger.debug(f"Browser {index}: Successfully clicked checkbox in iframe with selector '{selector}'")
                                    driver.switch_to.default_content()
                                    return True
                            except Exception as e:
                                if self.debug:
                                    logger.debug(f"Browser {index}: Iframe checkbox selector '{selector}' failed: {str(e)}")
                                continue

                        # Switch back to default content
                        driver.switch_to.default_content()

                        # Если не смогли кликнуть чекбокс, пробуем клик по iframe
                        try:
                            if self.debug:
                                logger.debug(f"Browser {index}: Trying to click iframe directly as fallback")
                            ActionChains(driver).click(iframe_element).perform()
                            return True
                        except Exception as e:
                            if self.debug:
                                logger.debug(f"Browser {index}: Iframe direct click failed: {str(e)}")

                    except Exception as e:
                        if self.debug:
                            logger.debug(f"Browser {index}: Failed to access iframe content: {str(e)}")
                        try:
                            driver.switch_to.default_content()
                        except:
                            pass

            except Exception as e:
                if self.debug:
                    logger.debug(f"Browser {index}: General iframe search failed: {str(e)}")

            return False

        return await asyncio.get_event_loop().run_in_executor(None, click_checkbox)

    async def _safe_click(self, driver, selector: str, index: int):
        """Selenium-based safe click"""
        def safe_click():
            try:
                if selector.startswith("//"):
                    # XPath selector
                    elements = driver.find_elements(By.XPATH, selector)
                else:
                    # CSS selector
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)

                if elements:
                    ActionChains(driver).click(elements[0]).perform()
                    return True
            except Exception as e:
                if self.debug and "Can't query n-th element" not in str(e):
                    logger.debug(f"Browser {index}: Safe click failed for '{selector}': {str(e)}")
            return False

        return await asyncio.get_event_loop().run_in_executor(None, safe_click)

    async def _js_click(self, driver, index: int):
        """JavaScript click execution"""
        def js_click():
            try:
                driver.execute_script("document.querySelector('.cf-turnstile')?.click()")
                return True
            except Exception as e:
                if self.debug:
                    logger.debug(f"Browser {index}: JS click failed: {str(e)}")
                return False

        return await asyncio.get_event_loop().run_in_executor(None, js_click)

    async def _try_click_strategies(self, driver, index: int):
        strategies = [
            ('checkbox_click', lambda: self._find_and_click_checkbox(driver, index)),
            ('direct_widget', lambda: self._safe_click(driver, '.cf-turnstile', index)),
            ('iframe_click', lambda: self._safe_click(driver, 'iframe[src*="turnstile"]', index)),
            ('js_click', lambda: self._js_click(driver, index)),
            ('sitekey_attr', lambda: self._safe_click(driver, '[data-sitekey]', index)),
            ('any_turnstile', lambda: self._safe_click(driver, '*[class*="turnstile"]', index)),
            ('xpath_click', lambda: self._safe_click(driver, "//div[@class='cf-turnstile']", index))
        ]

        for strategy_name, strategy_func in strategies:
            try:
                result = await strategy_func()
                if result is True or result is None:
                    if self.debug:
                        logger.debug(f"Browser {index}: Click strategy '{strategy_name}' succeeded")
                    return True
            except Exception as e:
                if self.debug:
                    logger.debug(f"Browser {index}: Click strategy '{strategy_name}' failed: {str(e)}")
                continue

        return False

    async def _load_captcha_overlay(self, driver, websiteKey: str, action: str = '', index: int = 0):
        """Create CAPTCHA overlay"""
        def create_overlay():
            script = f"""
            const existing = document.querySelector('#captcha-overlay');
            if (existing) existing.remove();

            const overlay = document.createElement('div');
            overlay.id = 'captcha-overlay';
            overlay.style.position = 'absolute';
            overlay.style.top = '0';
            overlay.style.left = '0';
            overlay.style.width = '100vw';
            overlay.style.height = '100vh';
            overlay.style.backgroundColor = 'rgba(0, 0, 0, 0.5)';
            overlay.style.display = 'block';
            overlay.style.justifyContent = 'center';
            overlay.style.alignItems = 'center';
            overlay.style.zIndex = '1000';

            const captchaDiv = document.createElement('div');
            captchaDiv.className = 'cf-turnstile';
            captchaDiv.setAttribute('data-sitekey', '{websiteKey}');
            captchaDiv.setAttribute('data-callback', 'onCaptchaSuccess');
            captchaDiv.setAttribute('data-action', '{action}');

            overlay.appendChild(captchaDiv);
            document.body.appendChild(overlay);

            const script = document.createElement('script');
            script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js';
            script.async = true;
            script.defer = true;
            document.head.appendChild(script);
            """

            driver.execute_script(script)
            if self.debug:
                logger.debug(f"Browser {index}: Created CAPTCHA overlay with sitekey: {websiteKey}")

        await asyncio.get_event_loop().run_in_executor(None, create_overlay)

    async def _solve_turnstile(self, task_id: str, url: str, sitekey: str, action: Optional[str] = None, cdata: Optional[str] = None):
        """Solve the Turnstile challenge."""
        index, browser, browser_config = await self.browser_pool.get()

        try:
            # For undetected chromedriver, check if browser session is still valid
            try:
                browser.current_url  # This will throw if browser is closed
            except Exception:
                if self.debug:
                    logger.warning(f"Browser {index}: Browser session invalid, skipping")
                await self.browser_pool.put((index, browser, browser_config))
                await save_result(task_id, "turnstile", {"value": "CAPTCHA_FAIL", "elapsed_time": 0})
                return
        except Exception as e:
            if self.debug:
                logger.warning(f"Browser {index}: Cannot check browser state: {str(e)}")

        # For Selenium, we need to handle proxy by creating a new driver instance
        # Since proxy configuration requires restarting the browser, we skip proxy for now
        # and focus on IPv6 configuration which was already handled during browser init

        # Configure IPv6 if enabled
        ipv6_address = None
        if self.ipv6_support and SUBNETS_IPV6:
            ipv6_address = generate_ipv6_address()
            if self.debug:
                logger.debug(f"Browser {index}: Generated IPv6 address: {ipv6_address}")
                logger.debug(f"Browser {index}: Available IPv6 subnets: {', '.join(SUBNETS_IPV6)}")
                logger.debug(f"Browser {index}: IPv6 support active - browser configured to prefer IPv6 connections")
        elif self.ipv6_support and not SUBNETS_IPV6:
            if self.debug:
                logger.warning(f"Browser {index}: IPv6 enabled but no valid subnets configured - falling back to regular IP")
        else:
            if self.debug:
                logger.debug(f"Browser {index}: IPv6 not enabled - using default IP resolution")

        # Test IP address if IPv6 is enabled or debug is active
        if self.ipv6_support or self.debug:
            await self._test_browser_ip(browser, index)

        # Set window size for Chrome-based browsers
        if self.browser_type in ['chromium', 'chrome', 'msedge']:
            def set_window_size():
                try:
                    browser.set_window_size(500, 100)
                    if self.debug:
                        logger.debug(f"Browser {index}: Set window size to 500x100")
                except Exception as e:
                    if self.debug:
                        logger.debug(f"Browser {index}: Could not set window size: {e}")

            await asyncio.get_event_loop().run_in_executor(None, set_window_size)

        start_time = time.time()

        try:
            if self.debug:
                logger.debug(f"Browser {index}: Starting Turnstile solve for URL: {url} with Sitekey: {sitekey} | Action: {action} | Cdata: {cdata}")

            if self.debug:
                logger.debug(f"Browser {index}: Loading real website directly: {url}")

            # Navigate to the target URL using Selenium
            def navigate_to_url():
                browser.get(url)

            await asyncio.get_event_loop().run_in_executor(None, navigate_to_url)

            # Wait for page to load
            await asyncio.sleep(3)

            max_attempts = 20

            for attempt in range(max_attempts):
                try:
                    # Find token elements using Selenium
                    def find_token_elements():
                        return browser.find_elements(By.CSS_SELECTOR, 'input[name="cf-turnstile-response"]')

                    token_elements = await asyncio.get_event_loop().run_in_executor(None, find_token_elements)
                    count = len(token_elements)

                    if count == 0:
                        if self.debug:
                            logger.debug(f"Browser {index}: No token elements found on attempt {attempt + 1}")
                    elif count == 1:
                        # Check single element token
                        try:
                            def get_token_value():
                                return token_elements[0].get_attribute('value')

                            token = await asyncio.get_event_loop().run_in_executor(None, get_token_value)
                            if token:
                                elapsed_time = round(time.time() - start_time, 3)
                                success_msg = f"Browser {index}: Successfully solved captcha - {COLORS.get('MAGENTA')}{token[:10]}{COLORS.get('RESET')} in {COLORS.get('GREEN')}{elapsed_time}{COLORS.get('RESET')} Seconds"
                                safe_log_success(success_msg)
                                await save_result(task_id, "turnstile", {"value": token, "elapsed_time": elapsed_time})
                                return
                        except Exception as e:
                            if self.debug:
                                logger.debug(f"Browser {index}: Single token element check failed: {str(e)}")
                    else:
                        # Check multiple elements
                        if self.debug:
                            logger.debug(f"Browser {index}: Found {count} token elements, checking all")

                        for i in range(count):
                            try:
                                def get_element_token(idx):
                                    return token_elements[idx].get_attribute('value')

                                element_token = await asyncio.get_event_loop().run_in_executor(None, get_element_token, i)
                                if element_token:
                                    elapsed_time = round(time.time() - start_time, 3)
                                    success_msg = f"Browser {index}: Successfully solved captcha - {COLORS.get('MAGENTA')}{element_token[:10]}{COLORS.get('RESET')} in {COLORS.get('GREEN')}{elapsed_time}{COLORS.get('RESET')} Seconds"
                                    safe_log_success(success_msg)
                                    await save_result(task_id, "turnstile", {"value": element_token, "elapsed_time": elapsed_time})
                                    return
                            except Exception as e:
                                if self.debug:
                                    logger.debug(f"Browser {index}: Token element {i} check failed: {str(e)}")
                                continue

                    # Click strategies every 3 attempts
                    if attempt > 2 and attempt % 3 == 0:
                        click_success = await self._try_click_strategies(browser, index)
                        if not click_success and self.debug:
                            logger.debug(f"Browser {index}: All click strategies failed on attempt {attempt + 1}")

                    # Fallback overlay on attempt 10
                    if attempt == 10:
                        try:
                            current_count = len(await asyncio.get_event_loop().run_in_executor(None, find_token_elements))
                            if current_count == 0:
                                if self.debug:
                                    logger.debug(f"Browser {index}: Creating overlay as fallback strategy")
                                await self._load_captcha_overlay(browser, sitekey, action or '', index)
                                await asyncio.sleep(2)
                        except Exception as e:
                            if self.debug:
                                logger.debug(f"Browser {index}: Fallback overlay creation failed: {str(e)}")

                    # Adaptive waiting
                    wait_time = min(0.5 + (attempt * 0.05), 2.0)
                    await asyncio.sleep(wait_time)

                    if self.debug and attempt % 5 == 0:
                        logger.debug(f"Browser {index}: Attempt {attempt + 1}/{max_attempts} - No valid token yet")

                except Exception as e:
                    if self.debug:
                        logger.debug(f"Browser {index}: Attempt {attempt + 1} error: {str(e)}")
                    continue

            elapsed_time = round(time.time() - start_time, 3)
            await save_result(task_id, "turnstile", {"value": "CAPTCHA_FAIL", "elapsed_time": elapsed_time})
            if self.debug:
                logger.error(f"Browser {index}: Error solving Turnstile in {COLORS.get('RED')}{elapsed_time}{COLORS.get('RESET')} Seconds")
        except Exception as e:
            elapsed_time = round(time.time() - start_time, 3)
            await save_result(task_id, "turnstile", {"value": "CAPTCHA_FAIL", "elapsed_time": elapsed_time})
            if self.debug:
                logger.error(f"Browser {index}: Error solving Turnstile: {str(e)}")
        finally:
            if self.debug:
                logger.debug(f"Browser {index}: Cleaning up and returning browser to pool")

            try:
                # For Selenium, we don't need to close context, just return the browser
                try:
                    browser.current_url  # Check if browser is still alive
                    await self.browser_pool.put((index, browser, browser_config))
                    if self.debug:
                        logger.debug(f"Browser {index}: Browser returned to pool")
                except Exception:
                    if self.debug:
                        logger.warning(f"Browser {index}: Browser disconnected, not returning to pool")
            except Exception as e:
                if self.debug:
                    logger.warning(f"Browser {index}: Error returning browser to pool: {str(e)}")






    async def process_turnstile(self):
        """Handle the /turnstile endpoint requests."""
        url = request.args.get('url')
        sitekey = request.args.get('sitekey')
        action = request.args.get('action')
        cdata = request.args.get('cdata')

        if not url or not sitekey:
            return jsonify({
                "errorId": 1,
                "errorCode": "ERROR_WRONG_PAGEURL",
                "errorDescription": "Both 'url' and 'sitekey' are required"
            }), 200

        task_id = str(uuid.uuid4())
        await save_result(task_id, "turnstile", {
            "status": "CAPTCHA_NOT_READY",
            "createTime": int(time.time()),
            "url": url,
            "sitekey": sitekey,
            "action": action,
            "cdata": cdata
        })

        try:
            # Create task in the current event loop
            loop = asyncio.get_event_loop()
            loop.create_task(self._solve_turnstile(task_id=task_id, url=url, sitekey=sitekey, action=action, cdata=cdata))

            if self.debug:
                logger.debug(f"Request completed with taskid {task_id}.")
            return jsonify({
                "errorId": 0,
                "taskId": task_id
            }), 200
        except Exception as e:
            logger.error(f"Unexpected error processing request: {str(e)}")
            return jsonify({
                "errorId": 1,
                "errorCode": "ERROR_UNKNOWN",
                "errorDescription": str(e)
            }), 200

    async def get_result(self):
        """Return solved data"""
        task_id = request.args.get('id')

        if not task_id:
            return jsonify({
                "errorId": 1,
                "errorCode": "ERROR_WRONG_CAPTCHA_ID",
                "errorDescription": "Invalid task ID/Request parameter"
            }), 200

        result = await load_result(task_id)
        if not result:
            return jsonify({
                "errorId": 1,
                "errorCode": "ERROR_CAPTCHA_UNSOLVABLE",
                "errorDescription": "Task not found"
            }), 200

        if result == "CAPTCHA_NOT_READY" or (isinstance(result, dict) and result.get("status") == "CAPTCHA_NOT_READY"):
            return jsonify({"status": "processing"}), 200

        if isinstance(result, dict) and result.get("value") == "CAPTCHA_FAIL":
            return jsonify({
                "errorId": 1,
                "errorCode": "ERROR_CAPTCHA_UNSOLVABLE",
                "errorDescription": "Workers could not solve the Captcha"
            }), 200

        if isinstance(result, dict) and result.get("value") and result.get("value") != "CAPTCHA_FAIL":
            return jsonify({
                "errorId": 0,
                "status": "ready",
                "solution": {
                    "token": result["value"]
                }
            }), 200
        else:
            return jsonify({
                "errorId": 1,
                "errorCode": "ERROR_CAPTCHA_UNSOLVABLE",
                "errorDescription": "Workers could not solve the Captcha"
            }), 200

    

    @staticmethod
    async def index():
        """Serve the API documentation page."""
        return """
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Turnstile Solver API</title>
                <script src="https://cdn.tailwindcss.com"></script>
            </head>
            <body class="bg-gray-900 text-gray-200 min-h-screen flex items-center justify-center">
                <div class="bg-gray-800 p-8 rounded-lg shadow-md max-w-2xl w-full border border-red-500">
                    <h1 class="text-3xl font-bold mb-6 text-center text-red-500">Welcome to Turnstile Solver API</h1>

                    <p class="mb-4 text-gray-300">To use the turnstile service, send a GET request to 
                       <code class="bg-red-700 text-white px-2 py-1 rounded">/turnstile</code> with the following query parameters:</p>

                    <ul class="list-disc pl-6 mb-6 text-gray-300">
                        <li><strong>url</strong>: The URL where Turnstile is to be validated</li>
                        <li><strong>sitekey</strong>: The site key for Turnstile</li>
                    </ul>

                    <div class="bg-gray-700 p-4 rounded-lg mb-6 border border-red-500">
                        <p class="font-semibold mb-2 text-red-400">Example usage:</p>
                        <code class="text-sm break-all text-red-300">/turnstile?url=https://example.com&sitekey=sitekey</code>
                    </div>


                    <div class="bg-gray-700 p-4 rounded-lg mb-6">
                        <p class="text-gray-200 font-semibold mb-3">📢 Connect with Us</p>
                        <div class="space-y-2 text-sm">
                            <p class="text-gray-300">
                                📢 <strong>Channel:</strong> 
                                <a href="https://t.me/D3_vin" class="text-red-300 hover:underline">https://t.me/D3_vin</a> 
                                - Latest updates and releases
                            </p>
                            <p class="text-gray-300">
                                💬 <strong>Chat:</strong> 
                                <a href="https://t.me/D3vin_chat" class="text-red-300 hover:underline">https://t.me/D3vin_chat</a> 
                                - Community support and discussions
                            </p>
                            <p class="text-gray-300">
                                📁 <strong>GitHub:</strong> 
                                <a href="https://github.com/D3-vin" class="text-red-300 hover:underline">https://github.com/D3-vin</a> 
                                - Source code and development
                            </p>
                        </div>
                    </div>
                </div>
            </body>
            </html>
        """


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Turnstile API Server")

    parser.add_argument('--no-headless', action='store_true', help='Run the browser with GUI (disable headless mode). By default, headless mode is enabled.')
    parser.add_argument('--useragent', type=str, help='User-Agent string (if not specified, random configuration is used)')
    parser.add_argument('--debug', action='store_true', help='Enable or disable debug mode for additional logging and troubleshooting information (default: False)')
    parser.add_argument('--browser_type', type=str, default='chromium', help='Specify the browser type for the solver. Supported options: chromium, chrome, msedge (default: chromium)')
    parser.add_argument('--thread', type=int, default=4, help='Set the number of browser threads to use for multi-threaded mode. Increasing this will speed up execution but requires more resources (default: 1)')
    parser.add_argument('--proxy', action='store_true', help='Enable proxy support for the solver (Default: False)')
    parser.add_argument('--ipv6', action='store_true', help='Enable IPv6 support for the solver (Default: False)')
    parser.add_argument('--random', action='store_true', help='Use random User-Agent and Sec-CH-UA configuration from pool')
    parser.add_argument('--browser', type=str, help='Specify browser name to use (e.g., chrome, firefox)')
    parser.add_argument('--version', type=str, help='Specify browser version to use (e.g., 139, 141)')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Specify the IP address where the API solver runs. (Default: 127.0.0.1)')
    parser.add_argument('--port', type=str, default='5072', help='Set the port for the API solver to listen on. (Default: 5072)')
    return parser.parse_args()


def create_app(headless: bool, useragent: str, debug: bool, browser_type: str, thread: int, proxy_support: bool, ipv6_support: bool, use_random_config: bool, browser_name: str, browser_version: str) -> Quart:
    server = TurnstileAPIServer(headless=headless, useragent=useragent, debug=debug, browser_type=browser_type, thread=thread, proxy_support=proxy_support, ipv6_support=ipv6_support, use_random_config=use_random_config, browser_name=browser_name, browser_version=browser_version)
    return server.app


if __name__ == '__main__':
    args = parse_args()
    browser_types = [
        'chromium',
        'chrome',
        'msedge',
    ]
    if args.browser_type not in browser_types:
        logger.error(f"Unknown browser type: {COLORS.get('RED')}{args.browser_type}{COLORS.get('RESET')} Available browser types: {browser_types}")
    else:
        app = create_app(
            headless=not args.no_headless, 
            debug=args.debug, 
            useragent=args.useragent, 
            browser_type=args.browser_type, 
            thread=args.thread, 
            proxy_support=args.proxy,
            ipv6_support=args.ipv6,
            use_random_config=args.random,
            browser_name=args.browser,
            browser_version=args.version
        )
        app.run(host=args.host, port=int(args.port))
