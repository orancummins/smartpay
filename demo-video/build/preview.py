import asyncio, sys, json
from playwright.async_api import async_playwright
times = [float(x) for x in sys.argv[1].split(',')]
tag = sys.argv[2] if len(sys.argv)>2 else 'p'
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--font-render-hinting=none'])
        pg = await b.new_page(viewport={'width':1920,'height':1080}, device_scale_factor=1)
        errs=[]; pg.on('pageerror', lambda e: errs.append(str(e))); pg.on('console', lambda m: errs.append(m.text) if m.type=='error' else None)
        await pg.goto('http://127.0.0.1:9030/stage.html', wait_until='load')
        await pg.wait_for_function('window.READY === true', timeout=60000)
        await pg.evaluate('document.fonts.ready')
        for t in times:
            await pg.evaluate(f'seek({t})')
            await pg.wait_for_timeout(60)
            await pg.screenshot(path=f'prev/{tag}_{t:06.1f}.jpg', type='jpeg', quality=85)
        print('errors:', errs[:5]); print('dbg', await pg.evaluate('JSON.stringify(window._dbg)'))
        await b.close()
asyncio.run(main())
