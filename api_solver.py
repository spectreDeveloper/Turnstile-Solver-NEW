import os
import sys
import time
import uuid
import random
import logging
import asyncio
from typing import Optional, Union
import argparse
from quart import Quart, request, jsonify
from camoufox.async_api import AsyncCamoufox
from patchright.async_api import async_playwright
from db_results import init_db, save_result, load_result, cleanup_old_results
from browser_configs import browser_config
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.align import Align
from rich import box


COLORS = {
    'MAGENTA': '\033[35m',
    'BLUE': '\033[34m',
    'GREEN': '\033[32m',
    'YELLOW': '\033[33m',
    'RED': '\033[31m',
    'RESET': '\033[0m',
}


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
logger = logging.getLogger("TurnstileAPIServer")
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
logger.addHandler(handler)


class TurnstileAPIServer:

    def __init__(self, headless: bool, useragent: Optional[str], debug: bool, browser_type: str, thread: int, proxy_support: bool, use_random_config: bool = False, browser_name: Optional[str] = None, browser_version: Optional[str] = None):
        self.app = Quart(__name__)
        self.debug = debug
        self.browser_type = browser_type
        self.headless = headless
        self.thread_count = thread
        self.proxy_support = proxy_support
        self.browser_pool = asyncio.Queue()
        self.use_random_config = use_random_config
        self.browser_name = browser_name
        self.browser_version = browser_version
        self.console = Console()
        
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
        combined_text.append("1.0", style="green")
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

    async def load_captcha(self, page, website_key: str, action: str = ''):
        """Add Turnstile to existing page."""
        script = f"""
        window.captchaToken = null;
        window.turnstileWidget = null;
        
        window.onCaptchaSuccess = function(token) {{
            console.log('Captcha solved successfully, token:', token);
            window.captchaToken = token;
        }};
        
        window.onCaptchaError = function(error) {{
            console.log('Captcha error:', error);
        }};
        
        window.onCaptchaExpired = function() {{
            console.log('Captcha expired');
            window.captchaToken = null;
        }};
        
        // Удаляем существующие виджеты
        const existing = document.querySelectorAll('.cf-turnstile, [data-sitekey]');
        existing.forEach(el => el.remove());

        const captchaDiv = document.createElement('div');
        captchaDiv.className = 'cf-turnstile';
        captchaDiv.setAttribute('data-sitekey', '{website_key}');
        captchaDiv.setAttribute('data-callback', 'onCaptchaSuccess');
        captchaDiv.setAttribute('data-error-callback', 'onCaptchaError');
        captchaDiv.setAttribute('data-expired-callback', 'onCaptchaExpired');
        captchaDiv.setAttribute('data-action', '{action}');
        captchaDiv.style.position = 'fixed';
        captchaDiv.style.top = '20px';
        captchaDiv.style.right = '20px';
        captchaDiv.style.zIndex = '9999';
        captchaDiv.style.backgroundColor = 'white';
        captchaDiv.style.padding = '20px';
        captchaDiv.style.borderRadius = '8px';
        captchaDiv.style.boxShadow = '0 4px 12px rgba(0,0,0,0.3)';

        document.body.appendChild(captchaDiv);

        // Загружаем скрипт Turnstile если его нет
        if (!document.querySelector('script[src*="turnstile"]')) {{
            const script = document.createElement('script');
            script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js';
            script.async = true;
            script.defer = true;
            script.onload = function() {{
                console.log('Turnstile script loaded');
                // Принудительно рендерим виджет
                if (window.turnstile) {{
                    window.turnstileWidget = window.turnstile.render(captchaDiv, {{
                        sitekey: '{website_key}',
                        callback: window.onCaptchaSuccess,
                        'error-callback': window.onCaptchaError,
                        'expired-callback': window.onCaptchaExpired,
                        action: '{action}'
                    }});
                }}
            }};
            document.head.appendChild(script);
        }} else {{
            // Если скрипт уже загружен, сразу рендерим виджет
            if (window.turnstile) {{
                window.turnstileWidget = window.turnstile.render(captchaDiv, {{
                    sitekey: '{website_key}',
                    callback: window.onCaptchaSuccess,
                    'error-callback': window.onCaptchaError,
                    'expired-callback': window.onCaptchaExpired,
                    action: '{action}'
                }});
            }}
        }}
        """

        await page.evaluate(script)

    async def _wait_for_turnstile_token(self, page, browser_index: int, timeout: int = 30) -> str:
        """Wait for Turnstile token with improved detection and forced interaction."""
        locator = page.locator('input[name="cf-turnstile-response"]')
        start_time = time.time()
        
        token = ""
        attempt = 0
        clicked_widget = False
        
        while not token and (time.time() - start_time) < timeout:
            attempt += 1
            
            try:
                # Проверяем input поле
                token = await locator.input_value(timeout=500)
                if token:
                    if self.debug:
                        logger.debug(f'Browser {browser_index}: Got captcha token from input: {token[:10]}...')
                    return token
                    
                # Проверяем глобальную переменную
                token = await page.evaluate('() => window.captchaToken')
                if token:
                    if self.debug:
                        logger.debug(f'Browser {browser_index}: Got captcha token from global variable: {token[:10]}...')
                    return token
                    
                # Принудительно кликаем на виджет каждую попытку (как в старом коде)
                try:
                    # Используем XPath селектор как в старом коде
                    widget = page.locator("//div[@class='cf-turnstile']")
                    widget_count = await widget.count()
                    
                    if self.debug and attempt % 5 == 0:
                        logger.debug(f'Browser {browser_index}: Widget count: {widget_count}')
                    
                    if widget_count > 0:
                        await widget.click(timeout=1000)
                        if self.debug:
                            logger.debug(f'Browser {browser_index}: Clicked on Turnstile widget using XPath (attempt {attempt})')
                    else:
                        # Fallback на другие селекторы
                        selectors = [
                            '[data-sitekey]',
                            '.cf-turnstile iframe',
                            'iframe[src*="turnstile"]',
                            'div[class*="turnstile"]'
                        ]
                        
                        for selector in selectors:
                            widget = page.locator(selector)
                            count = await widget.count()
                            if count > 0:
                                await widget.first.click(timeout=1000)
                                if self.debug:
                                    logger.debug(f'Browser {browser_index}: Clicked on Turnstile widget using selector: {selector} (attempt {attempt})')
                                break
                        else:
                            if self.debug and attempt % 5 == 0:
                                logger.debug(f'Browser {browser_index}: No Turnstile widgets found (attempt {attempt})')
                            
                except Exception as e:
                    if self.debug:
                        logger.debug(f'Browser {browser_index}: Error clicking widget (attempt {attempt}): {str(e)}')
                
                # Проверяем, загружен ли Turnstile API (только в начале)
                if attempt == 1:
                    current_turnstile_loaded = await page.evaluate('() => typeof window.turnstile !== "undefined"')
                    if current_turnstile_loaded and self.debug:
                        logger.debug(f'Browser {browser_index}: Turnstile API is loaded and ready')
                    elif self.debug:
                        logger.debug(f'Browser {browser_index}: Turnstile API not detected, but widget should work')
                
                # Принудительно запускаем виджет если он не активен
                if attempt % 10 == 0:
                    try:
                        await page.evaluate('''
                            if (window.turnstile && window.turnstileWidget) {
                                try {
                                    window.turnstile.reset(window.turnstileWidget);
                                } catch(e) {
                                    console.log("Error resetting turnstile:", e);
                                }
                            }
                        ''')
                    except Exception as e:
                        if self.debug:
                            logger.debug(f'Browser {browser_index}: Error resetting turnstile: {str(e)}')
                    
                if self.debug and attempt % 5 == 0:
                    logger.debug(f'Browser {browser_index}: Attempt {attempt} - Waiting for Turnstile token...')
                    
            except Exception as e:
                if self.debug:
                    logger.debug(f'Browser {browser_index}: Token check error: {str(e)}')
                    
            # Добавляем небольшую задержку между попытками, как в старом коде
            await asyncio.sleep(0.5)
            
        if self.debug:
            logger.warning(f'Browser {browser_index}: Token not found within {timeout} seconds')
        return "CAPTCHA_FAIL"


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
            asyncio.create_task(self._periodic_cleanup())
            
        except Exception as e:
            logger.error(f"Failed to initialize browser: {str(e)}")
            raise

    async def _initialize_browser(self) -> None:
        """Initialize the browser and create the page pool."""
        playwright = None
        camoufox = None

        if self.browser_type in ['chromium', 'chrome', 'msedge']:
            playwright = await async_playwright().start()
        elif self.browser_type == "camoufox":
            camoufox = AsyncCamoufox(headless=self.headless)

        browser_configs = []
        for _ in range(self.thread_count):
            if self.browser_type in ['chromium', 'chrome', 'msedge']:
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
            else:
                # Для camoufox и других браузеров используем значения по умолчанию
                browser = self.browser_type
                version = 'custom'
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
            
            browser_args = [
                "--window-position=0,0",
                "--force-device-scale-factor=1"
            ]
            if config['useragent']:
                browser_args.append(f"--user-agent={config['useragent']}")
            
            browser = None
            if self.browser_type in ['chromium', 'chrome', 'msedge'] and playwright:
                browser = await playwright.chromium.launch(
                    channel=self.browser_type,
                    headless=self.headless,
                    args=browser_args
                )
            elif self.browser_type == "camoufox" and camoufox:
                browser = await camoufox.start()

            if browser:
                await self.browser_pool.put((i+1, browser, config))

            if self.debug:
                logger.info(f"Browser {i + 1} initialized successfully with {config['browser_name']} {config['browser_version']}")

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

    async def _solve_turnstile(self, task_id: str, url: str, sitekey: str, action: Optional[str] = None, cdata: Optional[str] = None):
        """Solve the Turnstile challenge."""
        proxy = None

        index, browser, browser_config = await self.browser_pool.get()
        
        try:
            if hasattr(browser, 'is_connected') and not browser.is_connected():
                if self.debug:
                    logger.warning(f"Browser {index}: Browser disconnected, skipping")
                await self.browser_pool.put((index, browser, browser_config))
                await save_result(task_id, "turnstile", {"value": "CAPTCHA_FAIL", "elapsed_time": 0})
                return
        except Exception as e:
            if self.debug:
                logger.warning(f"Browser {index}: Cannot check browser state: {str(e)}")

        if self.proxy_support:
            proxy_file_path = os.path.join(os.getcwd(), "proxies.txt")

            try:
                with open(proxy_file_path) as proxy_file:
                    proxies = [line.strip() for line in proxy_file if line.strip()]

                proxy = random.choice(proxies) if proxies else None
                
                if self.debug and proxy:
                    logger.debug(f"Browser {index}: Selected proxy: {proxy}")
                elif self.debug and not proxy:
                    logger.debug(f"Browser {index}: No proxies available")
                    
            except FileNotFoundError:
                logger.warning(f"Proxy file not found: {proxy_file_path}")
                proxy = None
            except Exception as e:
                logger.error(f"Error reading proxy file: {str(e)}")
                proxy = None

            if proxy:
                if '@' in proxy:
                    try:
                        scheme_part, auth_part = proxy.split('://')
                        auth, address = auth_part.split('@')
                        username, password = auth.split(':')
                        ip, port = address.split(':')
                        if self.debug:
                            logger.debug(f"Browser {index}: Creating context with proxy {scheme_part}://{ip}:{port} (auth: {username}:***)")
                        context_options = {
                            "proxy": {
                                "server": f"{scheme_part}://{ip}:{port}",
                                "username": username,
                                "password": password
                            },
                            "user_agent": browser_config['useragent']
                        }
                        
                        if browser_config['sec_ch_ua'] and browser_config['sec_ch_ua'].strip():
                            context_options['extra_http_headers'] = {
                                'sec-ch-ua': browser_config['sec_ch_ua']
                            }
                        
                        context = await browser.new_context(**context_options)
                    except ValueError:
                        raise ValueError(f"Invalid proxy format: {proxy}")
                else:
                    parts = proxy.split(':')
                    if len(parts) == 5:
                        proxy_scheme, proxy_ip, proxy_port, proxy_user, proxy_pass = parts
                        if self.debug:
                            logger.debug(f"Browser {index}: Creating context with proxy {proxy_scheme}://{proxy_ip}:{proxy_port} (auth: {proxy_user}:***)")
                        context_options = {
                            "proxy": {
                                "server": f"{proxy_scheme}://{proxy_ip}:{proxy_port}",
                                "username": proxy_user,
                                "password": proxy_pass
                            },
                            "user_agent": browser_config['useragent']
                        }
                        
                        if browser_config['sec_ch_ua'] and browser_config['sec_ch_ua'].strip():
                            context_options['extra_http_headers'] = {
                                'sec-ch-ua': browser_config['sec_ch_ua']
                            }
                        
                        context = await browser.new_context(**context_options)
                    elif len(parts) == 3:
                        if self.debug:
                            logger.debug(f"Browser {index}: Creating context with proxy {proxy}")
                        context_options = {
                            "proxy": {"server": f"{proxy}"},
                            "user_agent": browser_config['useragent']
                        }
                        
                        if browser_config['sec_ch_ua'] and browser_config['sec_ch_ua'].strip():
                            context_options['extra_http_headers'] = {
                                'sec-ch-ua': browser_config['sec_ch_ua']
                            }
                        
                        context = await browser.new_context(**context_options)
                    else:
                        raise ValueError(f"Invalid proxy format: {proxy}")
            else:
                if self.debug:
                    logger.debug(f"Browser {index}: Creating context without proxy")
                context_options = {"user_agent": browser_config['useragent']}
                
                if browser_config['sec_ch_ua'] and browser_config['sec_ch_ua'].strip():
                    context_options['extra_http_headers'] = {
                        'sec-ch-ua': browser_config['sec_ch_ua']
                    }
                
                context = await browser.new_context(**context_options)
        else:
            context_options = {"user_agent": browser_config['useragent']}
            
            if browser_config['sec_ch_ua'] and browser_config['sec_ch_ua'].strip():
                context_options['extra_http_headers'] = {
                    'sec-ch-ua': browser_config['sec_ch_ua']
                }
            
            context = await browser.new_context(**context_options)

        page = await context.new_page()
        
        await page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
        });
        
        window.chrome = {
            runtime: {},
            loadTimes: function() {},
            csi: function() {},
        };
        """)
        
        if self.browser_type in ['chromium', 'chrome', 'msedge']:
            await page.set_viewport_size({"width": 800, "height": 600})
            if self.debug:
                logger.debug(f"Browser {index}: Set viewport size to 800x600")

        start_time = time.time()

        try:
            if self.debug:
                logger.debug(f"Browser {index}: Starting Turnstile solve for URL: {url} with Sitekey: {sitekey} | Action: {action} | Cdata: {cdata} | Proxy: {proxy}")
                logger.debug(f"Browser {index}: Loading clean page")

            await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            
            # Ждем загрузки страницы и Turnstile API
            await asyncio.sleep(random.uniform(2.0, 3.0))
            
            # Проверяем, что страница загрузилась корректно
            page_title = await page.title()
            if self.debug:
                logger.debug(f"Browser {index}: Page loaded - Title: {page_title}")
            
            # Проверяем, есть ли уже Turnstile API на странице
            turnstile_loaded = await page.evaluate('() => typeof window.turnstile !== "undefined"')
            if turnstile_loaded and self.debug:
                logger.debug(f"Browser {index}: Turnstile API already loaded on page")
            elif self.debug:
                logger.debug(f"Browser {index}: Turnstile API not found on page, will load it with widget")

            if self.debug:
                logger.debug(f"Browser {index}: Checking for existing Turnstile")
                
                # Отладочная информация о содержимом страницы
                page_content = await page.content()
                if 'turnstile' in page_content.lower():
                    logger.debug(f"Browser {index}: Page contains 'turnstile' text")
                if 'cf-turnstile' in page_content:
                    logger.debug(f"Browser {index}: Page contains 'cf-turnstile' class")
                if 'data-sitekey' in page_content:
                    logger.debug(f"Browser {index}: Page contains 'data-sitekey' attribute")

            # Проверяем существующие Turnstile виджеты с расширенными селекторами
            turnstile_selectors = [
                '.cf-turnstile',
                '[data-sitekey]',
                'iframe[src*="turnstile"]',
                'iframe[src*="challenges.cloudflare.com"]',
                'div[class*="turnstile"]',
                'div[id*="turnstile"]'
            ]
            
            existing_turnstile = 0
            for selector in turnstile_selectors:
                count = await page.locator(selector).count()
                if count > 0:
                    existing_turnstile += count
                    if self.debug:
                        logger.debug(f"Browser {index}: Found {count} existing Turnstile widget(s) with selector: {selector}")
            
            existing_input = await page.locator('input[name="cf-turnstile-response"]').count()
            
            if existing_turnstile == 0:
                if self.debug:
                    logger.debug(f"Browser {index}: No existing Turnstile found, adding one")
                await self.load_captcha(page, sitekey, action or '')
            else:
                if self.debug:
                    logger.debug(f"Browser {index}: Found {existing_turnstile} existing Turnstile widget(s)")
                
                # Проверяем, есть ли уже готовый токен
                if existing_input > 0:
                    existing_token = await page.locator('input[name="cf-turnstile-response"]').input_value(timeout=1000)
                    if existing_token:
                        if self.debug:
                            logger.debug(f"Browser {index}: Found existing token: {existing_token[:10]}...")
                        elapsed_time = round(time.time() - start_time, 3)
                        logger.info(f"Browser {index}: Successfully solved captcha - {COLORS.get('MAGENTA')}{existing_token[:10]}{COLORS.get('RESET')} in {COLORS.get('GREEN')}{elapsed_time}{COLORS.get('RESET')} Seconds")
                        await save_result(task_id, "turnstile", {"value": existing_token, "elapsed_time": elapsed_time})
                        return
                
                # Дополнительная проверка токена в глобальной переменной
                global_token = await page.evaluate('() => window.captchaToken || window.turnstileToken')
                if global_token:
                    if self.debug:
                        logger.debug(f"Browser {index}: Found existing token in global variable: {global_token[:10]}...")
                    elapsed_time = round(time.time() - start_time, 3)
                    logger.info(f"Browser {index}: Successfully solved captcha - {COLORS.get('MAGENTA')}{global_token[:10]}{COLORS.get('RESET')} in {COLORS.get('GREEN')}{elapsed_time}{COLORS.get('RESET')} Seconds")
                    await save_result(task_id, "turnstile", {"value": global_token, "elapsed_time": elapsed_time})
                    return

            if self.debug:
                logger.debug(f"Browser {index}: Starting Turnstile response retrieval loop")

            # Проверяем, загрузился ли Turnstile API после добавления виджета
            if not turnstile_loaded:
                await asyncio.sleep(2.0)  # Даем время на загрузку API
                turnstile_loaded_after = await page.evaluate('() => typeof window.turnstile !== "undefined"')
                if turnstile_loaded_after and self.debug:
                    logger.debug(f"Browser {index}: Turnstile API loaded after adding widget")
                elif self.debug:
                    logger.debug(f"Browser {index}: Turnstile API still not loaded, but widget should work anyway")

            # Дополнительный клик сразу после загрузки, как в старом коде
            try:
                # Ждем немного для загрузки виджета
                await asyncio.sleep(1.0)
                
                widget = page.locator("//div[@class='cf-turnstile']")
                widget_count = await widget.count()
                
                if self.debug:
                    logger.debug(f"Browser {index}: Initial widget count: {widget_count}")
                
                if widget_count > 0:
                    await widget.click(timeout=1000)
                    if self.debug:
                        logger.debug(f"Browser {index}: Initial click on Turnstile widget")
                    await asyncio.sleep(0.5)
                else:
                    # Пробуем другие селекторы
                    selectors = ['[data-sitekey]', '.cf-turnstile iframe', 'iframe[src*="turnstile"]']
                    for selector in selectors:
                        widget = page.locator(selector)
                        if await widget.count() > 0:
                            await widget.first.click(timeout=1000)
                            if self.debug:
                                logger.debug(f"Browser {index}: Initial click using selector: {selector}")
                            break
                            
            except Exception as e:
                if self.debug:
                    logger.debug(f"Browser {index}: Error with initial click: {str(e)}")

            token = await self._wait_for_turnstile_token(page, index)
            
            if token and token != "CAPTCHA_FAIL":
                elapsed_time = round(time.time() - start_time, 3)
                logger.info(f"Browser {index}: Successfully solved captcha - {COLORS.get('MAGENTA')}{token[:10]}{COLORS.get('RESET')} in {COLORS.get('GREEN')}{elapsed_time}{COLORS.get('RESET')} Seconds")
                await save_result(task_id, "turnstile", {"value": token, "elapsed_time": elapsed_time})
            else:
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
                logger.debug(f"Browser {index}: Closing browser context and cleaning up")
            
            try:
                await context.close()
                if self.debug:
                    logger.debug(f"Browser {index}: Context closed successfully")
            except Exception as e:
                if self.debug:
                    logger.warning(f"Browser {index}: Error closing context: {str(e)}")
            
            # Возвращаем браузер в пул только если он еще подключен
            try:
                if hasattr(browser, 'is_connected') and browser.is_connected():
                    await self.browser_pool.put((index, browser, browser_config))
                    if self.debug:
                        logger.debug(f"Browser {index}: Browser returned to pool")
                else:
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
                "status": "error",
                "error": "Both 'url' and 'sitekey' are required"
            }), 400

        task_id = str(uuid.uuid4())
        await save_result(task_id, "turnstile", {"status": "CAPTCHA_NOT_READY"})

        try:
            asyncio.create_task(self._solve_turnstile(task_id=task_id, url=url, sitekey=sitekey, action=action, cdata=cdata))

            if self.debug:
                logger.debug(f"Request completed with taskid {task_id}.")
            return jsonify({"task_id": task_id}), 200
        except Exception as e:
            logger.error(f"Unexpected error processing request: {str(e)}")
            return jsonify({
                "status": "error",
                "error": str(e)
            }), 500

    async def get_result(self):
        """Return solved data"""
        task_id = request.args.get('id')

        if not task_id:
            return jsonify({"status": "error", "error": "Invalid task ID/Request parameter"}), 400

        result = await load_result(task_id)
        if not result:
            return jsonify({"status": "error", "error": "Task not found"}), 404

        if result == "CAPTCHA_NOT_READY" or (isinstance(result, dict) and result.get("status") == "CAPTCHA_NOT_READY"):
            return jsonify({"status": "processing"}), 200

        if isinstance(result, dict) and result.get("value") == "CAPTCHA_FAIL":
            return jsonify({"status": "fail", **result}), 422

        if isinstance(result, dict):
            return jsonify({"status": "ready", **result}), 200
        else:
            return jsonify({"status": "ready", "data": result}), 200

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
    parser.add_argument('--browser_type', type=str, default='chromium', help='Specify the browser type for the solver. Supported options: chromium, chrome, msedge, camoufox (default: chromium)')
    parser.add_argument('--thread', type=int, default=4, help='Set the number of browser threads to use for multi-threaded mode. Increasing this will speed up execution but requires more resources (default: 1)')
    parser.add_argument('--proxy', action='store_true', help='Enable proxy support for the solver (Default: False)')
    parser.add_argument('--random', action='store_true', help='Use random User-Agent and Sec-CH-UA configuration from pool')
    parser.add_argument('--browser', type=str, help='Specify browser name to use (e.g., chrome, firefox)')
    parser.add_argument('--version', type=str, help='Specify browser version to use (e.g., 139, 141)')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Specify the IP address where the API solver runs. (Default: 127.0.0.1)')
    parser.add_argument('--port', type=str, default='6080', help='Set the port for the API solver to listen on. (Default: 6080)')
    return parser.parse_args()


def create_app(headless: bool, useragent: str, debug: bool, browser_type: str, thread: int, proxy_support: bool, use_random_config: bool, browser_name: str, browser_version: str) -> Quart:
    server = TurnstileAPIServer(headless=headless, useragent=useragent, debug=debug, browser_type=browser_type, thread=thread, proxy_support=proxy_support, use_random_config=use_random_config, browser_name=browser_name, browser_version=browser_version)
    return server.app


if __name__ == '__main__':
    args = parse_args()
    browser_types = [
        'chromium',
        'chrome',
        'msedge',
        'camoufox',
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
            use_random_config=args.random,
            browser_name=args.browser,
            browser_version=args.version
        )
        app.run(host=args.host, port=int(args.port))
