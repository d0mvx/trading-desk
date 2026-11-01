import sys, asyncio
from playwright.async_api import async_playwright
sys.path.insert(0, "/workspace/desk2")
from desk import util
TOK = util.secret("app_token")
A = "6m7frLtvpHUNRfBHQHjtZZs812kVwKsY16gxPj6vpump"
SCREENS = [("home", "#/home"), ("agents", "#/agents"), ("auditor", f"#/audit/{A}"), ("coin", f"#/coin/{A}"), ("account", "#/account")]
async def main():
    errs = []
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        for state, port in (("normal", 8798), ("empty", 8797), ("error", 8798)):
            ctx = await b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True,
                user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")
            pg = await ctx.new_page()
            pg.on("console", lambda m, s=state: m.type == "error" and errs.append((s, m.text)))
            pg.on("pageerror", lambda e, s=state: errs.append((s, "PAGEERROR " + str(e.stack)[:600])))
            await pg.goto(f"http://127.0.0.1:{port}/#t={TOK}"); await pg.wait_for_timeout(1500)
            if state == "error":
                for name, h in SCREENS:
                    await pg.evaluate(f"location.hash = '{h}'"); await pg.wait_for_timeout(1200)
                await pg.route("**/api/**", lambda r: r.abort())
            for name, h in SCREENS:
                await pg.evaluate(f"location.hash = '{h}'"); await pg.wait_for_timeout(5200 if name == "auditor" else 1300)
                await pg.screenshot(path=f"shots/{name}_{state}.png")
            await ctx.close()
        await b.close()
    print("ERRORS", [e for e in errs if "ERR_FAILED" not in e[1] and "Failed to load resource" not in e[1]] )
asyncio.run(main())
