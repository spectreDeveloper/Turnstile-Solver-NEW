#!/usr/bin/env python3
"""
Browser Configurations
Browser configuration with User-Agent and Sec-CH-UA data for TLS fingerprinting
"""

import random
from typing import Dict, List, Tuple, Optional


class BrowserConfig:
    """Class for working with browser configurations"""
    
    SEC_CH_UA_CONFIGS = {
        "chrome": {
            "139": "\"Not;A=Brand\";v=\"99\", \"Google Chrome\";v=\"139\", \"Chromium\";v=\"139\"",
            "138": "\"Not)A;Brand\";v=\"8\", \"Chromium\";v=\"138\", \"Google Chrome\";v=\"138\"",
            "137": "\"Google Chrome\";v=\"137\", \"Chromium\";v=\"137\", \"Not/A)Brand\";v=\"24\"",
            "136": "\"Chromium\";v=\"136\", \"Google Chrome\";v=\"136\", \"Not.A/Brand\";v=\"99\""
        },
        "edge": {
            "139": "\"Not;A=Brand\";v=\"99\", \"Microsoft Edge\";v=\"139\", \"Chromium\";v=\"139\"",
            "138": "\"Not)A;Brand\";v=\"8\", \"Chromium\";v=\"138\", \"Microsoft Edge\";v=\"138\"",
            "137": "\"Microsoft Edge\";v=\"137\", \"Chromium\";v=\"137\", \"Not/A)Brand\";v=\"24\""
        },
        "avast": {
            "138": "\"Not)A;Brand\";v=\"8\", \"Chromium\";v=\"138\", \"Avast Secure Browser\";v=\"138\"",
            "137": "\"Avast Secure Browser\";v=\"137\", \"Chromium\";v=\"137\", \"Not/A)Brand\";v=\"24\""
        },
        "brave": {
            "139": "\"Not;A=Brand\";v=\"99\", \"Brave\";v=\"139\", \"Chromium\";v=\"139\"",
            "138": "\"Not)A;Brand\";v=\"8\", \"Chromium\";v=\"138\", \"Brave\";v=\"138\"",
            "137": "\"Brave\";v=\"137\", \"Chromium\";v=\"137\", \"Not/A)Brand\";v=\"24\""
        }
    }
    
    USER_AGENT_CONFIGS = {
        "chrome": {
            "139": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
            "138": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
            "137": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
            "136": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
        },
        "edge": {
            "139": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36 Edg/139.0.0.0",
            "138": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36 Edg/138.0.0.0",
            "137": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36 Edg/137.0.0.0"
        },
        "avast": {
            "138": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36 Avast/138.0.0.0",
            "137": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36 Avast/137.0.0.0"
        },
        "brave": {
            "139": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
            "138": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
            "137": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
        }
    }
    
    
    def __init__(self):
        self.available_browsers = list(self.USER_AGENT_CONFIGS.keys())
    
    def get_random_browser_config(self, browser_type=None) -> Tuple[str, str, str, str]:
        """
        Get random browser configuration
        
        Args:
            browser_type: Browser type for filtering (chrome, chromium, camoufox)
            
        Returns:
            Tuple[str, str, str, str]: (browser_name, version, user_agent, sec_ch_ua)
        """
        if browser_type in ['chrome', 'chromium', 'msedge', 'avast']:
            chromium_browsers = ['chrome', 'edge', 'avast', 'brave']
            browser = random.choice(chromium_browsers)
        elif browser_type == 'camoufox':
            return 'firefox', 'custom', '', ''
        else:
            browser = random.choice(self.available_browsers)
            
        versions = list(self.USER_AGENT_CONFIGS[browser].keys())
        version = random.choice(versions)
        
        user_agent = self.USER_AGENT_CONFIGS[browser][version]
        
        if version in self.SEC_CH_UA_CONFIGS.get(browser, {}):
            sec_ch_ua = self.SEC_CH_UA_CONFIGS[browser][version]
        else:
            sec_ch_ua = ""
            
        return browser, version, user_agent, sec_ch_ua
    
    def get_browser_config(self, browser: str, version: str) -> Optional[Tuple[str, str]]:

        try:
            user_agent = self.USER_AGENT_CONFIGS[browser][version]
            
            if version in self.SEC_CH_UA_CONFIGS.get(browser, {}):
                sec_ch_ua = self.SEC_CH_UA_CONFIGS[browser][version]
            else:
                sec_ch_ua = ""
                
            return user_agent, sec_ch_ua
        except KeyError:
            return None
    
    def get_all_configs(self) -> List[Tuple[str, str, str, str]]:

        configs = []
        for browser in self.available_browsers:
            for version in self.USER_AGENT_CONFIGS[browser].keys():
                user_agent = self.USER_AGENT_CONFIGS[browser][version]
                
                if version in self.SEC_CH_UA_CONFIGS.get(browser, {}):
                    sec_ch_ua = self.SEC_CH_UA_CONFIGS[browser][version]
                else:
                    sec_ch_ua = ""
                    
                configs.append((browser, version, user_agent, sec_ch_ua))
        
        return configs
    
    def get_browser_versions(self, browser: str) -> List[str]:

        return list(self.USER_AGENT_CONFIGS.get(browser, {}).keys())
    
    def get_available_browsers(self) -> List[str]:

        return self.available_browsers.copy()
    
    def print_all_configs(self):
        """Print all available configurations to console"""
        print("=== AVAILABLE BROWSER CONFIGURATIONS ===\n")
        
        for browser in self.available_browsers:
            print(f"🌐 {browser.upper()}:")
            for version in self.USER_AGENT_CONFIGS[browser].keys():
                user_agent = self.USER_AGENT_CONFIGS[browser][version]
                
                if version in self.SEC_CH_UA_CONFIGS.get(browser, {}):
                    sec_ch_ua = self.SEC_CH_UA_CONFIGS[browser][version]
                else:
                    sec_ch_ua = "NOT SUPPORTED"
                    
                print(f"  📱 Version {version}:")
                print(f"    User-Agent: {user_agent}")
                print(f"    Sec-CH-UA: {sec_ch_ua}")
                print()
            print("-" * 50)


browser_config = BrowserConfig()


if __name__ == '__main__':
    config = BrowserConfig()
    
    print("🎯 Random configuration:")
    browser, version, ua, sec_ua = config.get_random_browser_config()
    print(f"Browser: {browser} {version}")
    print(f"User-Agent: {ua}")
    print(f"Sec-CH-UA: {sec_ua}")
    print()
    
    print("📋 All available browsers:")
    for browser in config.get_available_browsers():
        versions = config.get_browser_versions(browser)
        print(f"  {browser}: {', '.join(versions)}")
    print()
    
    config.print_all_configs()
