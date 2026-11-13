// Isolated browser contract test; all account and password responses are fake.
// Run: NODE_PATH=<playwright installation> node webui/native_local_browser_test.js
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const root = path.resolve(__dirname)
const origin = 'http://127.0.0.1:18942'
const generatedPassword = 'fixture-new-managed-password'
let revealCount = 0
let setCount = 0
let loginCount = 0
let managed = false
let nativeAuthorized = true

async function main() {
    const browser = await chromium.launch({executablePath: process.env.CHROMIUM_EXECUTABLE || undefined, headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage']})
    try {
        const page = await browser.newPage()
        const errors = []
        page.on('pageerror', error => errors.push(error.message))
        await page.addInitScript(() => {
            Object.defineProperty(navigator, 'clipboard', {value: {writeText: async text => { window.fixtureCopiedText = text }}})
        })
        await page.route(origin + '/**', async route => {
            const request = route.request()
            const url = new URL(request.url())
            let body
            let contentType = 'application/json'
            if (url.pathname === '/webui/user/native_accounts') {
                if (!nativeAuthorized) { await route.fulfill({status: 403, body: ''}); return }
                body = JSON.stringify({accounts: [{user_id: 123456789, rank: 42}, {user_id: 222222222, rank: 9}]})
            }
            else if (url.pathname === '/webui/user/login' && request.method() === 'POST') {
                loginCount++
                assert.match(request.postData(), /123456789/)
                assert(!request.postData().includes(generatedPassword))
                body = JSON.stringify({response: 'fixture-session-key', error: null})
            } else if (url.pathname === '/webui/user/login') {
                contentType = 'text/html'; body = fs.readFileSync(path.join(root, 'user/login.html'), 'utf8')
            } else if (url.pathname === '/webui/native_local.js') {
                contentType = 'text/javascript'; body = fs.readFileSync(path.join(root, 'native_local.js'), 'utf8')
            } else if (url.pathname === '/webui/user/native_connection') body = JSON.stringify({user_id: 123456789, server_address: 'http://127.0.0.1:8080', address_note: 'fixture reachable address', has_managed_password: managed, server_public_key: '-----BEGIN PUBLIC KEY-----\nfixture\n-----END PUBLIC KEY-----'})
            else if (url.pathname === '/webui/user/native_password/set') {
                setCount++
                assert.match(request.postData(), /confirm_password_change/)
                managed = true
                body = JSON.stringify({has_managed_password: true})
            } else if (url.pathname === '/webui/user/native_password/reveal') {
                revealCount++
                body = JSON.stringify({password: generatedPassword})
            } else if (url.pathname === '/webui/user' || url.pathname === '/webui/user/client_connection') {
                contentType = 'text/html'
                const panel = url.pathname.endsWith('client_connection') ? fs.readFileSync(path.join(root, 'user/native_connection.html'), 'utf8') : '<p id="fixture-account-hub">Account hub</p>'
                body = fs.readFileSync(path.join(root, 'user/logged_in_user.html'), 'utf8').replace('{{ .body | noescape }}', panel)
            } else if (url.pathname === '/webui/admin/native_access') body = JSON.stringify({native_local: true})
            else if (url.pathname === '/webui/admin/config_editor') {
                contentType = 'text/html'
                body = fs.readFileSync(path.join(root, 'admin/logged_in_admin.html'), 'utf8').replace('{{ .body | noescape }}', '<input id="fixture-config" value="existing">')
            } else { body = ''; contentType = 'text/css' }
            await route.fulfill({status: 200, contentType, body})
        })
        await page.goto(origin + '/webui/user/login?l=en')
        await page.locator('body[data-elichika-local-access="true"]').waitFor()
        assert.equal(await page.locator('#login_form').isVisible(), false)
        await page.locator('#native-account-filter').fill('123')
        assert.equal(await page.locator('#native-account-list button:visible').count(), 1)
        await page.locator('#native-account-list button:visible').click()
        await page.locator('#fixture-account-hub').waitFor()
        assert.equal(loginCount, 1)
        await page.goto(origin + '/webui/user/client_connection?l=en')
        await page.waitForFunction(() => document.getElementById('native-client-address').value !== '')
        assert.equal(revealCount, 0)
        assert.equal(setCount, 0)
        assert.equal(await page.locator('#native-client-password').inputValue(), '')
        assert.equal(await page.locator('#native-client-password').getAttribute('type'), 'password')
        assert.equal(await page.locator('#native-reveal-password').isDisabled(), true)
        await page.locator('details').first().locator('summary').click()
        await page.getByRole('button', {name: 'Set / generate client login password', exact: true}).click()
        assert.equal(setCount, 0)
        await page.locator('#native-confirm-password').check()
        await page.getByRole('button', {name: 'Set / generate client login password', exact: true}).click()
        await page.waitForFunction(() => !document.getElementById('native-reveal-password').disabled)
        assert.equal(setCount, 1)
        assert.equal(revealCount, 0)
        await page.locator('#native-reveal-password').click()
        await page.waitForFunction(() => document.getElementById('native-client-password').type === 'text')
        assert.equal(await page.locator('#native-client-password').inputValue(), generatedPassword)
        await page.locator('#native-reveal-password').click()
        assert.equal(await page.locator('#native-client-password').inputValue(), '')
        await page.locator('#native-copy-connection').click()
        await page.waitForFunction(() => !!window.fixtureCopiedText)
        const copied = await page.evaluate(() => window.fixtureCopiedText)
        assert(copied.includes('http://127.0.0.1:8080') && copied.includes('123456789') && copied.includes(generatedPassword))
        assert(!copied.includes('0.0.0.0') && !copied.includes('PUBLIC KEY'))
        assert.equal(await page.evaluate(() => Object.values(localStorage).some(value => value.includes('fixture-new-managed-password')) || Object.values(sessionStorage).some(value => value.includes('fixture-new-managed-password'))), false)
        await page.goto(origin + '/webui/user/client_connection?l=ko')
        await page.getByRole('heading', {name: '클라이언트 로그인 / 이전'}).waitFor()
        assert.equal(new URL(page.url()).searchParams.get('l'), 'ko')
        assert.equal(revealCount, 2)
        assert.equal(await page.locator('#native-client-password').inputValue(), '')
        await page.goto(origin + '/webui/admin/config_editor?l=en')
        await page.locator('body[data-elichika-local-access="true"]').waitFor()
        assert.equal(await page.locator('#fixture-config').isVisible(), true)
        nativeAuthorized = false
        await page.goto(origin + '/webui/user/login?l=en')
        await page.locator('#login_form:visible').waitFor()
        assert.equal(await page.locator('#native-account-picker').isVisible(), false)
        assert.equal(await page.locator('#user_password').isVisible(), true)
        assert.equal(errors.length, 0, errors.join('\n'))
        console.log(JSON.stringify({ok: true, accountClickLogin: loginCount === 1, explicitPasswordChange: setCount === 1, lazyPasswordReads: revealCount === 2, plaintextBrowserStorage: false, nativeAdminWithoutPassword: true}))
    } finally { await browser.close() }
}
main().catch(error => { console.error(error.stack); process.exitCode = 1 })
