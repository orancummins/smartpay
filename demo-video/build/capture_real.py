"""Produce the real tool outputs, the real ChatGPT component and dashboard screenshots used by the stage.
Run from the smartpay repo root with app.dashboard_server listening on 127.0.0.1:9023."""
import asyncio, json, os, sys
sys.path.insert(0, os.getcwd())
from app.services.smartpay import SmartPayService
from app import config, widget
from playwright.async_api import async_playwright
os.makedirs('real', exist_ok=True)
s = SmartPayService()
json.dump(s.optimise_itinerary(config.DEMO_CUSTOMER_ID, None, None), open('real/optimise_itinerary.json','w'), indent=1, default=str)
json.dump(s.optimise_wallet(config.DEMO_CUSTOMER_ID), open('real/optimise_wallet.json','w'), indent=1, default=str)
json.dump(s.get_wallet(config.DEMO_CUSTOMER_ID), open('real/get_wallet.json','w'), indent=1, default=str)
json.dump(s.get_financial_profile(config.DEMO_CUSTOMER_ID), open('real/get_financial_profile.json','w'), indent=1, default=str)
open('real/widget_raw.html','w').write(widget.widget_html())
CSS = ".topbar{position:static!important}.retro-habits{position:static!important}.campaign-preview{position:static!important}"
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(); pg = await b.new_page(viewport={'width':1600,'height':1000})
        await pg.goto('http://127.0.0.1:9023/demo/alex', wait_until='networkidle'); await pg.wait_for_timeout(1500)
        for tid in ['future-toggle','priceless-toggle']: await pg.click('#'+tid); await pg.wait_for_timeout(500)
        await pg.add_style_tag(content=CSS); await pg.evaluate('window.scrollTo(0,0)'); await pg.wait_for_timeout(800)
        await pg.screenshot(path='real/dashboard_v2.png', full_page=True)
        await pg.goto('http://127.0.0.1:9023/admin', wait_until='networkidle'); await pg.wait_for_timeout(1200)
        await pg.add_style_tag(content=CSS); await pg.screenshot(path='real/admin_dashboard.png', full_page=True)
        await pg.click('button[data-view="campaigns"]'); await pg.wait_for_timeout(1500)
        await pg.evaluate('window.scrollTo(0,0)'); await pg.screenshot(path='real/admin_campaigns.png', full_page=True)
        await b.close()
asyncio.run(main())
