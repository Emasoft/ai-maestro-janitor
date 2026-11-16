// WHY this file exists: each test below pins ONE secret the shield knowingly does not hide today (the entries of ../KNOWN-MISSES.md), so a
// change that starts hiding it turns the test red instead of passing unnoticed. A test that goes red because the miss was FIXED is not a
// regression: turn it into a positive test (assert the hit, in patterns.test.ts) and delete its entry from ../KNOWN-MISSES.md in the SAME
// commit, because tests/test_secret_shield_known_misses.py fails when an entry and its test do not match by name. Titles starting with
// KNOWN DEFECT are open defects with their own card (not accepted misses): they follow the same rule when the card is fixed.
// The fakes are fixed, assembled at run time where they start with a vendor prefix, and checked for length and alphabet, so the miss is
// proved on a value of the shape the entry names. No assertion prints a fake: they compare booleans.
import { describe, expect, test } from 'claude-code/testing'

import { countOf, mark, redact, redactBlocks, redactDeep } from '../patterns'
import * as ai from '../rules/ai'
import * as cloud from '../rules/cloud'
import * as codeHosts from '../rules/code-hosts'
import * as devServices from '../rules/dev-services'
import * as keyMaterial from '../rules/key-material'
import * as messaging from '../rules/messaging-payments'
import type { Rule } from '../rules/rule'

const j = (...parts: string[]) => parts.join('')
const BS = '\\'

// Every fake goes through fake(): a value under 8 characters, or one used twice, stops the file from loading, so two tests never share a value.
const registered = new Set<string>()
const fake = (value: string): string => {
  if (value.length < 8 || registered.has(value)) throw new Error(`a fake of ${value.length} characters is too short or used twice`)
  registered.add(value)
  return value
}

const shown = (text: string, piece: string): boolean => redact(text).text.indexOf(piece) !== -1
const hidden = (text: string, piece: string): boolean => {
  const done = redact(text)
  return done.text.indexOf(piece) === -1 && countOf(done.hits) > 0
}
const hiddenAs = (text: string, piece: string, kind: string): boolean => {
  const out = redact(text).text
  return out.indexOf(piece) === -1 && out.indexOf(mark(kind)) !== -1
}
// A failing check names its case: the message reads "<label>: false" against "<label>: true".
const check = (label: string, ok: boolean): void => {
  expect(`${label}: ${ok}`).toBe(`${label}: true`)
}

describe('known misses: formats and names the shield does not hide on their own', () => {
  test('KNOWN MISS standalone-github-legacy-40hex: a bare 40-hex legacy GitHub token is not hidden, the same token after its name is', () => {
    const token = fake('1a36494e24f084b17d16799053515679a1f2b37d')
    expect(/^[0-9a-f]{40}$/.test(token)).toBe(true)
    expect(shown(`see ${token} here`, token)).toBe(true)
    const frames = [`GITHUB_TOKEN=${token}`, `{"GITHUB_TOKEN": "${token}"}`, `Authorization: token ${token}`, `https://x-access-token:${token}@github.com/o/r`]
    for (const frame of frames) check(`hidden in ${frame.slice(0, 14)}`, hidden(frame, token))
  })

  test('KNOWN MISS standalone-aws-secret-40: a bare 40-character AWS secret access key is not hidden, the same key after its name is', () => {
    const secret = fake('qK6pIv+yiGnRiQUuHm/wDkZ9zDAlQnXPqTYQB6uP')
    expect(/^[A-Za-z0-9/+]{40}$/.test(secret)).toBe(true)
    expect(shown(`see ${secret} here`, secret)).toBe(true)
    const frames = [`aws_secret_access_key=${secret}`, `AWS_SECRET_ACCESS_KEY=${secret}`, `aws_secret_access_key = ${secret}`, `aws_secret_access_key: ${secret}`, `{"SecretAccessKey": "${secret}"}`]
    for (const frame of frames) check(`hidden in ${frame.slice(0, 14)}`, hidden(frame, secret))
  })

  test('KNOWN MISS standalone-aws-session-token: a bare AWS session token with no leading shape is not hidden, the same token after its name is', () => {
    const token = fake('XD2VDLm5zZWEc3LAmvml62YWLPYd09HBRJE1PwdiPYwNwphxzT24tO5a4KMVoEcAH8beue4EiyRNWswi9ph1CZ+rXg35gK1PLPsdExbURUn/Bi6CVu5IoYprM51MSOYr03Vv7B/gzx019U87P5SI2PLAOW+ZegTczss58nAO8gtkcb2lxM45B50Z6aZRWeTSuatGYrBx6F3zNYij5IIM1hGv2thtKMQLAZk/v9iuYfAk3AYpI9DYjq69Bs2eug3gyF5P6y6SmH/vmQ9EFTlfQuykyfmuNEQf4DHDEx39MeLsWngb1CuQDsbv/klyLn+RJxrge+kM6fZmeVQPDfVtWrXEhLyXwKhJHMgL')
    expect(/^[A-Za-z0-9/+]+$/.test(token)).toBe(true)
    expect(token.length >= 100).toBe(true)
    expect(shown(`see ${token} here`, token)).toBe(true)
    const frames = [`aws_session_token=${token}`, `AWS_SESSION_TOKEN=${token}`, `export AWS_SESSION_TOKEN="${token}"`, `{"SessionToken": "${token}"}`, `X-Amz-Security-Token: ${token}`]
    for (const frame of frames) check(`hidden in ${frame.slice(0, 14)}`, hidden(frame, token))
  })

  test('KNOWN MISS standalone-google-client-secret-without-prefix: a bare 24-character Google client secret without its prefix is not hidden, with the prefix it is', () => {
    const secret = fake('8VvUy5SlMYQHCO8CCZcfHr4N')
    expect(/^[A-Za-z0-9_-]+$/.test(secret)).toBe(true)
    expect(secret.length >= 20).toBe(true)
    expect(shown(`see ${secret} here`, secret)).toBe(true)
    expect(hiddenAs(`see ${j('GOC', 'SPX-')}${secret} here`, secret, 'google-oauth-client-secret')).toBe(true)
    expect(hidden(`client_secret=${secret}`, secret)).toBe(true)
  })

  test('KNOWN MISS google-refresh-legacy-single-slash: a legacy Google refresh token starting 1/ is not hidden, with the current 1//0 start it is', () => {
    const tail = fake('ZljnwHTzmtvR1i5s5qOFB4v8_iLd2pLhIKBcAT51rbhtW')
    expect(shown(`see 1/${tail} here`, `1/${tail}`)).toBe(true)
    expect(hiddenAs(`see 1//0${tail} here`, tail, 'google-oauth-refresh-token')).toBe(true)
    expect(hidden(`refresh_token=1/${tail}`, tail)).toBe(true)
  })

  test('KNOWN MISS google-access-over-2048: the part of a Google access token past its 2048-character first segment stays visible', () => {
    const secret = fake('qITo5aijI6j45N4_KZWLWAeL5svVVrQ8i629WOk6WqS29Hoo-XmrQdCGRS8lUhPHdvIUjwEeo1qK59wU81_D2bofC7d-BvkT053udPEPoNa_YUdJigO6mmvMIlClFrJmqK6zGOF2tIjeEKIIZ4mkbArQP2dEF0_wwbKt7IO1EbuBFRUxw5BAqm06aDEuZQeXZHp_YPBkvE7ZmkWo7ehC3lV6-duTVzOFMg6rxsgMWohkKhNGd22z0ABDp9aM9e2PXyvE_jePNK9dmMO6D4I5Nc4qG_XORpXO35Un48QneeT3y6jw5yNmYHlIXB1lcwHnEhJ8yKkK9APC_owXOJxjLILFKfNGtAYY7aIHRP3PAbsU1-wjrA5e3CYhytHOyUqVM7bCcphPTYsVo_2A1Bliv-aqrDybJgFTVsnPicfja0rd7ocrT4rhdp1k2R-E8jjmhORBw8IDZCzafmZZozCJdyvu84X4phPsNWzcvNDt9fuePWZev5rglJX8yuvAQ8BglqR0emnomqawbKmAAcsJ9PVZig2IftIPVcjPyj8ky54LSekxdoeqlNmNld3uIv5oFN8M57GWraMjkuFSP_bvL-1M8RWX7qgZeG1Dz0vJ7CI70DDCqY6BmmDZMV8Ke3lv_FwLbAEnSa7dHDSgzRjZbaZHaQvCu42u4oa9b_UYcrD9bAScj3NogHaTohCUewVqFWdPcgUWZxAmv8PBr6eLBpyxi76ilMTmd47RtV3cIDE8TZMAPt2peglIPgKJaEusDX7euIhZ5JEjBj2OIMXH6eyUJxTHb37ipR2Iixp47Kcb7DDV791Q9JBEw5qbm50c8sb1nsVLd_qDzo0pw6dN6Hs8USn72fsELWNd_0KG2BbzxlyenULg6J6S9hifV5QfXlNxSTPY87OS0rEYHTPCUjjIJOAy9rgOjoDIuPTy0ImIYNx1j94-leWSvbG0IzytvmH0wlQ9lbscBv8nKgvZwR0PxULF65cH1SesDuge2f9Y7YEOycliVbrFVLpjnBEdt3F6-oiIaUkuhtlzSVVBNHDXTbYX25VlZVF3k5tku49ZgcPB38YUs00ufMizBTs4Wo_qh83jG5mU0KCxV9mKvOMEE59e_-1Wt0hH8eGHJdDQfZjnnNR9i2icXsCn6hddFjrIzx_Q0dPLDSiu5tmPg3Kg4dhoeVAwCMu8368uNwaJnbwv2Ni1DY4zjFdQ_oYYhJflPufc7aTtQjSrqHgf2PGtuSB57PvSzUy8qjX39nWOu89TxIgag60kEFce8rFy-_zkUFygTvl7aApH3H9of64QM3hLHg85Jx3AlM9hU5ibAEs4qAzsIyhHRsdpF29n1UhuEi16iTMwxKfQcCVQXNmN7XvhcyWnfcdzgkwk1lWab9LFoM95l6FoqNDH34aJALLljEI4RDSxkce6lkXotGKrZLyyitFD_8CEjvwgHVOOAZffeurfJYXmtWZ37NH-KWNNIXqYcYC1azIojvH2IzUQq5lIUFmm7AOgcmz9yxRNFdje-8iatMNQ_AZiepxvURRu7zR28cv74B4M7WcbersMatWkbJnfvWwu2DOChaL57JYK2o7Ocg-ChHJ811-wkRSQ4s4Ke0K6uUdioEGRjLpOFNdQBslk1W8gndfNmf3yc7RmdoHnFkXItfoS_epg_cTH4TqBFv09M4wPwPx8e_Qx8-fJnA4rPc7if-GrDmb5-RyCXAAMuCdbV9WUOi0f1_PFNkN_NH-N6KdcEBLGTBXGfQhnA78XzChmhHT_BPAWb3bct9o03g54YeobxnUPGqCoFkaN-8vu7pTnQ6VOyoxT57oRHAHob_fA_7rBsXmlx1lHP52qzuw4u8SZUp4a8D4WOztaqXEzsYDR5b2XRGnUgPIQCCfhraRWEMuEt0-9lG6ZqVHlOLHdRql4fakYprZgW5CjbLspwquuEV70VrSrcKkzrqguu6Tjgq3NwXf9G7yW3lyC8mX654lJbWXeGtO1uAZEPYk7tp7BZ87vJKyHeZcQBmiC8Sjs-1FmVsRtALc6s9itO-1qqGeSlkYwADpI8us2JpE8whzir_uvwnxUuy-qVmmrWXSZx1l2sF-MsQjRIqZj')
    expect(secret.length).toBe(2100)
    const out = redact(`see ya29.${secret} here`).text
    expect(out.indexOf(mark('google-oauth-access-token') + secret.slice(2048)) !== -1).toBe(true)
    expect(out.indexOf(secret.slice(0, 40))).toBe(-1)
    expect(hidden(`access_token=ya29.${secret}`, secret)).toBe(true)
  })

  test('KNOWN MISS google-access-dotted-segment-over-512: the part of a dotted Google access token segment past 512 characters stays visible', () => {
    const first = fake('u4lZrSHZOcK-VIdDRVjJuot-Onk-n-')
    const segment = fake('KaQfM8tmlmiKfJd2YYREDp9ogu-7lBQCcTjrC4AZ0kUtchxiPgHWnV6uykIkwejsnh_Q5rL6hdNoa6L2-6xzNWhnKPkR4mQDtdWhcOa3QVUUgwqbgfQS2QvSzDsatLxuNmhWG620Rk5aNxdKqrVZVVeQbVMMz0393yEz8YzpzMlXJgLafCIBH0-sbyxJsY-irE_W73JtGxjC4SnjLjDxk4UrofsiLTfCTWD7izNL3b2wVKwIZ1ItTgmY-vvUrmpCKTKmlA71Dn83QnEnNyZ-xe3IzketPa4cV2S67vAy2vRdcBTve6Y91xL3NzgeGQIQSfXmyKspjOJOed828zGSJMVYU7mrrPlZe8FbThoRq1ff9hMO-0d0rBl5vlyoDzP2GqDnR-Z-sN5_X_VVpy0GODCrgZXfjcVBqh6Dc8zpUF0_wPitK3XnEzgs_MJSYD_1IVxExkQ6y7aePwDV-dABrwE_gGpSCP_5lMRe7Mx9IV_ZrQNLoaYZbDkI1yXFmufmT84F96R8UyFGXGjHj1zgmWpcKJ8acQFa8pLWD1kkbmXHaZeBonvxAWZmotJeTgMZMbCJXRYpDxbIEzKwo4bvrwvk')
    expect(segment.length).toBe(600)
    const out = redact(`see ya29.${first}.${segment} here`).text
    expect(out.indexOf(mark('google-oauth-access-token') + segment.slice(512)) !== -1).toBe(true)
    expect(out.indexOf(segment.slice(0, 40))).toBe(-1)
    expect(hidden(`access_token=ya29.${first}.${segment}`, segment)).toBe(true)
  })

  test('KNOWN MISS google-access-more-than-four-dotted-segments: the fifth dotted segment of a Google access token stays visible', () => {
    const first = fake('D9mzAmkEYk1cm1twSVq3z65Gfxohi4')
    const segments = [fake('KCL4COIEKujv_q8na7fT'), fake('kSyxTwoUHClhyLhLl8h-'), fake('dxhaKg2DtvVIkhlODX_h'), fake('g9QIIxrOBppClovz3zk9'), fake('_hng4_O77I-rEq5xGnZP')]
    expect(segments.length).toBe(5)
    const out = redact(`see ya29.${first}.${segments.join('.')} here`).text
    expect(out.indexOf(mark('google-oauth-access-token') + '.' + segments[4]) !== -1).toBe(true)
    expect(out.indexOf(segments[0])).toBe(-1)
    expect(hidden(`access_token=ya29.${first}.${segments.join('.')}`, segments[4])).toBe(true)
  })

  test('KNOWN MISS google-refresh-over-512: the part of a Google refresh token past 512 characters stays visible', () => {
    const secret = fake('_YFr8-pm13EqBYjK866-Nr1zSGE9_4EoaLlKbEpKRWVKxFOGNowi0Wj9gcWjDvnYP625nDf0NqlvBFvRtaNjkN_XwWpxd-qrtlRNgV3VwaIxckbvcKfM7YyA8jog82Vd7eX_X3y1xgIjpVB4pS0i2TG5FVc7TIx7bmuVhUUie-waCyyBr6NhTnaxKUQyHBsQPv-FQlLS6PT5SWEil10MmoxXOWCfmoY3EubLqkF-zuhGZg0Jw03TIFbR6Uf9Cm8D8kpOlvVyh3w4YUMACLzbU8EYcG3OXDcfVSEAhDnRreZZm9NchXd6Gt78xZVC1QRttuQ15GvmWL-cjsygxp0ExfbyIvXQL_9k7dNWPTj8NkOOxhON-OUV03t-dhGHng3iO5M5WEL58jty489nDqmFd5ymHRGMLfZmjgHy07nSd7NZWzPNgdan4NZUMEwaPQ2Xtgocbt4u36QMfF4FaRB4SHjigdtga3af3OW2kn4NLJRKMUmhTevSHil-kx-j71tZMaLkpf41nH2lXwjKN6bGlfhrbxvB9kt2kGo6cdG24wtQ8odbTps7pWIoIQNX2lEEKET-8c1a78ZvNov5cZCcMsgZ')
    expect(secret.length).toBe(600)
    const out = redact(`see 1//0${secret} here`).text
    expect(out.indexOf(mark('google-oauth-refresh-token') + secret.slice(512)) !== -1).toBe(true)
    expect(out.indexOf(secret.slice(0, 40))).toBe(-1)
    expect(hidden(`refresh_token=1//0${secret}`, secret)).toBe(true)
  })

  test('KNOWN MISS google-refresh-after-plus: a Google refresh token right after a plus sign is not hidden, without the plus it is', () => {
    const tail = fake('OT3Sx4oRo3JqPXlnT9wAlytYV_8k1R9QiDNZwrhcnU_r7eqYmC')
    expect(shown(`see +1//0${tail} here`, `1//0${tail}`)).toBe(true)
    expect(hiddenAs(`see 1//0${tail} here`, tail, 'google-oauth-refresh-token')).toBe(true)
    expect(hidden(`refresh_token=1//0${tail}`, tail)).toBe(true)
  })

  test('KNOWN MISS name-ending-in-name: the value of a key whose name ends in name stays visible, the same value after password= is hidden', () => {
    const value = fake('omYfyHWtdvp2L3z8zZ')
    expect(shown(`myTokenName=${value}`, value)).toBe(true)
    expect(shown(`myTokenName: "${value}"`, value)).toBe(true)
    expect(hidden(`password=${value}`, value)).toBe(true)
    expect(hidden(`my_token=${value}`, value)).toBe(true)
  })

  test('KNOWN MISS weak-word-value: a lowercase word of under 16 characters with no digit after password= stays visible, in a connection string it is hidden', () => {
    const weak = fake('lanternfish')
    expect(/^[a-z]{8,15}$/.test(weak)).toBe(true)
    expect(/\d/.test(weak)).toBe(false)
    expect(weak.length < 16).toBe(true)
    expect(shown(`password=${weak}`, weak)).toBe(true)
    expect(shown(`password: ${weak}`, weak)).toBe(true)
    expect(hidden(`Server=h;Password=${weak};Database=d`, weak)).toBe(true)
    // One digit makes it 6 or more characters with a digit, which the check accepts.
    expect(hidden(`password=${weak}7`, weak)).toBe(true)
  })

  test('KNOWN MISS unquoted-dotted-identifier: an unquoted dotted identifier after password= stays visible, quoted it is hidden, an unquoted JWT is hidden', () => {
    const dotted = fake('QwmzTnRpLk' + '.' + 'VbXcJdHsAf')
    expect(/^[A-Za-z]{10}\.[A-Za-z]{10}$/.test(dotted)).toBe(true)
    expect(dotted.length).toBe(21)
    const unquoted = redact(`password=${dotted}`)
    expect(unquoted.text.indexOf(dotted) !== -1).toBe(true)
    expect(unquoted.hits.assignment ?? 0).toBe(0)
    expect(hiddenAs(`password="${dotted}"`, dotted, 'assignment')).toBe(true)
    // Control: a dotted token form is hidden by its own token rule, which runs before the assignment pass.
    const token = fake(j('eyJ', 'Nk3vBq8WzXr2', '.', 'eyJ', 'Pd5LmT9cYh4s', '.', 'Gf7RtQ2nXw8KzB4vJd6M'))
    const withToken = redact(`password=${token}`)
    expect(withToken.text.indexOf(token)).toBe(-1)
    expect(withToken.hits.jwt).toBe(1)
  })

  test('KNOWN MISS gitlab-body-under-20-chars: a GitLab prefix followed by a 19-character body is not hidden, with 20 characters it is', () => {
    const short = fake('Hd7Lq2VmX9sKc4TnB6w')
    const edge = fake('Hd7Lq2VmX9sKc4TnB6wZ')
    expect(short.length).toBe(19)
    expect(edge.length).toBe(20)
    expect(shown(`see ${j('gl', 'pat-')}${short} end`, short)).toBe(true)
    check('20 characters hidden', hiddenAs(`see ${j('gl', 'pat-')}${edge} end`, edge, 'gitlab-pat'))
  })

  test('KNOWN MISS gitlab-legacy-unprefixed-token: a bare 20-character legacy GitLab token is not hidden, after GITLAB_TOKEN= it is', () => {
    const legacy = fake('kTq4Zm9Wd2VxN7pRb3Hs')
    expect(/^[A-Za-z0-9]{20}$/.test(legacy)).toBe(true)
    expect(shown(`see ${legacy} here`, legacy)).toBe(true)
    check('hidden after GITLAB_TOKEN=', hiddenAs(`GITLAB_TOKEN=${legacy}`, legacy, 'assignment'))
  })
})

describe('known misses: a Bearer value the shield does not read across a line break', () => {
  test('KNOWN MISS bearer-value-on-next-line: a token wrapped onto the next line after Bearer stays visible, on the same line it is hidden', () => {
    const value = fake('abcdefg1' + 'hijk')
    expect(shown('Bearer\n' + value, value)).toBe(true)
    check('the same-line value is hidden', hiddenAs('Bearer ' + value + ' x', value, 'bearer-token'))
  })
})

describe('known misses: PEM headers and URL userinfo the shield does not read', () => {
  test('KNOWN MISS private-key-header-shapes: a PEM header with a leading space, a double space or a word glued to PRIVATE is not hidden, a standard header is', () => {
    const body = fake('MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7')
    const block = (head: string) => `${j('-----BEGIN ', head, '-----')}\n${body}\n${j('-----END ', head, '-----')}`
    for (const head of [' PRIVATE KEY', 'RSA  PRIVATE KEY', 'XPRIVATE KEY']) check(`visible with the header ${JSON.stringify(head)}`, shown(block(head), body))
    check('hidden with a standard header', hiddenAs(block('RSA PRIVATE KEY'), body, 'private-key'))
  })

  test('KNOWN MISS url-password-port-then-path: a URL password starting with up to 5 digits and a slash or a query is read as a port and is not hidden, after 6 digits or a letter it is', () => {
    const password = fake('Kxq7mZw4Rt')
    for (const lead of ['9/', '12345/', '9?a=']) check(`visible after ${lead}`, shown(`postgres://u:${lead}${password}@db.acme.io/app`, password))
    for (const lead of ['123456/', 'ab/']) check(`hidden after ${lead}`, hiddenAs(`postgres://u:${lead}${password}@db.acme.io/app`, password, 'url-password'))
  })

  test('KNOWN MISS url-userinfo-quote-backtick-bracket: a URL password holding a double quote or a backtick, or a user part holding a quote, a backtick or an opening bracket, is not hidden, a plain one is', () => {
    const password = fake('Hs9Lc3Yb7Vn')
    const tick = String.fromCharCode(96)
    const userinfos = [`u:pa"${password}`, `u:pa${tick}${password}`, `us"er:${password}`, `us${tick}er:${password}`, `us[er:${password}`]
    for (const userinfo of userinfos) check(`visible in ${userinfo.replace(password, 'P')}`, shown(`postgres://${userinfo}@db.acme.io/app`, password))
    check('hidden with a plain user and password', hiddenAs(`postgres://u:${password}@db.acme.io/app`, password, 'url-password'))
  })
})

describe('known misses: copies of a hidden secret the shield does not follow', () => {
  const definition = (value: string): string => `API_KEY=${value}`

  test('KNOWN MISS prop-separate-call: a secret hidden in one call stays visible when a second call copies it', () => {
    const value = fake('kOgEsa4fshoJBrNOhzYCPavp')
    expect(hidden(definition(value), value)).toBe(true)
    expect(shown(`echo ${value}`, value)).toBe(true)
    expect(hidden(`${definition(value)}\necho ${value}`, value)).toBe(true)
  })

  test('KNOWN MISS prop-split-copy: a copy of a hidden secret cut by a line break stays visible, an intact copy is hidden', () => {
    const value = fake('n0GhHR9NzT7S2pUlhkx2edIL')
    const out = redact(`${definition(value)}\ncopy: ${value.slice(0, 12)}\n${value.slice(12)}`).text
    expect(out.indexOf(value.slice(0, 12)) !== -1).toBe(true)
    expect(out.indexOf(value.slice(12)) !== -1).toBe(true)
    expect(hidden(`${definition(value)}\ncopy: ${value}`, value)).toBe(true)
  })

  test('KNOWN MISS prop-truncated-copy: the head or the tail of a hidden secret shown with dots stays visible, an intact copy is hidden', () => {
    const value = fake('Pc0mItiGcVT4dCTfvyRxL76O')
    const head = value.slice(0, 16)
    const tail = value.slice(-16)
    expect(shown(`${definition(value)}\nshown: ${head}...`, head)).toBe(true)
    expect(shown(`${definition(value)}\nshown: ...${tail}`, tail)).toBe(true)
    expect(hidden(`${definition(value)}\nshown: ${value}`, value)).toBe(true)
  })

  test('KNOWN MISS prop-base64-form: the base64 form of a hidden secret, alone or after user:, stays visible, an intact copy is hidden', () => {
    const value = fake('ztMadjKo1PgCJapGBKlWcoDl')
    const plain = fake('enRNYWRqS28xUGdDSmFwR0JLbFdjb0Rs')
    const basic = fake('dXNlcjp6dE1hZGpLbzFQZ0NKYXBHQktsV2NvRGw=')
    expect(shown(`${definition(value)}\necho ${plain} | base64 -d`, plain)).toBe(true)
    expect(shown(`${definition(value)}\necho ${basic} | base64 -d`, basic)).toBe(true)
    expect(hidden(`${definition(value)}\necho ${value} | base64 -d`, value)).toBe(true)
  })

  test('KNOWN MISS prop-json-decoded-form: the decoded form of a hidden JSON value with an escape stays visible, the escaped copy is hidden', () => {
    const cases: Array<[string, string, string, string]> = [
      ['quote', BS + '"', '"', fake('67xwWGAZCp') + '|' + fake('yQmr9X3igz')],
      ['newline', BS + 'n', '\n', fake('mlugSzjzx4') + '|' + fake('idj7vNZUZG')],
      ['unicode', BS + 'u00e9', 'é', fake('qYwFH4xAwu') + '|' + fake('KMjxlz0l42')],
    ]
    for (const [name, escaped, decoded, parts] of cases) {
      const [first, second] = parts.split('|')
      const raw = first + escaped + second
      const pair = `{"user": "bob", "password": "${raw}"}`
      check(`${name} decoded form visible`, shown(`${pair}\ndecoded: ${first}${decoded}${second}`, first + decoded + second))
      check(`${name} escaped copy hidden`, hidden(`${pair}\nescaped copy: ${raw}`, raw))
    }
  })

  test('KNOWN MISS prop-overlap: the part of a text that only the second of two overlapping hidden values covers stays visible', () => {
    const first = fake('Q7z21w9mBYD2')
    const shared = fake('czBNADeD0fbp')
    const last = fake('ZWs2QTuPYIi2')
    const head = `${definition(first + shared)}\nDB_PASSWORD=${shared + last}\n`
    expect(shown(`${head}copy: ${first}${shared}${last}`, last)).toBe(true)
    expect(hidden(`${head}copy: ${first}${shared}`, first + shared)).toBe(true)
  })

  test('KNOWN MISS prop-refused-shapes: a copy of a hidden value of a shape the propagation refuses stays visible, the definition line is hidden', () => {
    // Each value is hidden where it is defined and refused only when it is hunted for elsewhere. The two quoted rows are hidden only when quoted.
    const shapes: Array<[string, string, boolean]> = [
      ['lowercase-word-slug', fake(['zrnfhfcz', 'axsxjbtc', 'ubszawtx', 'jydqtzpk'].join('-')), false],
      ['letters-only-identifier', fake('WtXLTyJhgRBHRgeMXJSX'), false],
      ['email-shaped', fake('mZGSTH8K' + '@' + 'dmhyfqcr' + '.com'), false],
      ['host-port-shaped', fake('81oMxxK2Sw' + ':' + '69522'), false],
      ['slash-base64-without-digit', fake('SVFGEKENs' + '/' + 'rTVCZVdKU'), false],
      ['leading-slash-base64', fake('/' + 'Cyl4glid7PWoSyecOe58'), false],
      ['contains-://', fake('4y3xyfTl' + '://' + 'v2c8Sa7X'), false],
      ['digits-only', fake('0632241268928063'), false],
      ['shorter-than-10', fake('xCQC0yLG'), false],
      ['dotted-domain-like', fake('75' + 'DwfEPg' + '.' + 'kYB7xlYy' + '.' + 'emhufaqd'), false],
      ['dotted-identifier', fake('GhBSmgdHau' + '.' + 'HgpdVRFurz'), true],
      ['no-letter-digit-pair-under-16', fake('bHXa' + '+' + 'kwPc' + '!' + 'UKa'), true],
    ]
    expect(shapes.length).toBe(12)
    for (const [name, value, quoted] of shapes) {
      const line = quoted ? `password="${value}"` : `password=${value}`
      check(`${name} definition line hidden`, hidden(line, value))
      check(`${name} copy visible`, shown(`${line}\necho ${value}`, `echo ${value}`))
    }
  })

})

describe('known defects: secrets the shield misses by a bug with its own card', () => {
  const wrap = (levels: number, leaf: unknown): unknown => {
    let node = leaf
    for (let i = 0; i < levels; i++) node = { c: node }
    return node
  }

  test('KNOWN DEFECT TRDD-UBWU9AQC deep-nesting-over-12: a token in a JSON value nested 13 levels deep is not hidden, at 12 levels it is', () => {
    const body = fake('Djabu7fyQyBzMJBBqZXJLZXgah6LQp3ZeVWT')
    const leaf = { t: `see ${j('gh', 'p_')}${body} here` }
    expect(JSON.stringify(redactDeep(wrap(13, leaf)).value).indexOf(body) !== -1).toBe(true)
    expect(JSON.stringify(redactDeep(wrap(12, leaf)).value).indexOf(body)).toBe(-1)
  })

  test('KNOWN DEFECT TRDD-0VOXC39W nontext-blocks: a token in a tool_use input or a thinking block is not hidden, in a text block it is', () => {
    const body = fake('uRjG5TDbWiCBy6r2AhrgcG3A7sGf5AZzhNhL')
    const text = `see ${j('gh', 'p_')}${body} here`
    const asToolUse = { type: 'tool_use', id: 't1', name: 'Bash', input: { command: text } }
    const asThinking = { type: 'thinking', thinking: text, signature: 'sig' }
    const asText = { type: 'text', text }
    expect(JSON.stringify(redactBlocks([asToolUse]).content).indexOf(body) !== -1).toBe(true)
    expect(JSON.stringify(redactBlocks([asThinking]).content).indexOf(body) !== -1).toBe(true)
    expect(JSON.stringify(redactBlocks([asText]).content).indexOf(body)).toBe(-1)
  })

  test('KNOWN DEFECT TRDD-5VZTPXBJ escape-boundary: a valid token right after a backslash-n, %22 or a backslash-t is not hidden by any rule that starts with a word boundary or a lookbehind', () => {
    const rules: Record<string, Rule> = { ...ai, ...cloud, ...codeHosts, ...devServices, ...keyMaterial, ...messaging }
    const tokens: Record<string, { lead?: string; prefix: string; secret: string }> = {
      awsAccessKey: { prefix: j('AK', 'IA'), secret: fake('84853HRPO22WAJW5') },
      awsSecretKeyAssignment: { lead: 'aws_secret_access_key=', prefix: '', secret: fake('pM+uNn+4ahMBfbr6hkIAKSDAHk5RdiBrn81YR2MW') },
      googleApiKey: { prefix: j('AI', 'za'), secret: fake('SqtqEFxrKAlI5BkuiBoidaV9U0lNhrjbehC') },
      googleOAuthClientSecret: { prefix: j('GOC', 'SPX-'), secret: fake('9XMkd3dbf4S8Zm1mmgVyblmkhllX') },
      googleOAuthAccessToken: { prefix: j('ya', '29.'), secret: fake('PPReReFaShyhBDxsELTwOxSyZwzIHoenHUu09tOn') },
      googleOAuthRefreshToken: { prefix: '1//0', secret: fake('-Qv9Fl7FVDQZDMRdk_i7hgxqwnQGtCx25qYqWNRrNbcwMjStdS') },
      githubTokenClassic: { prefix: j('gh', 'p_'), secret: fake('Ya7P3Y9cF9JnmXeekmflpukrwSFtXiUA5PkO') },
      githubTokenFineGrained: { prefix: j('github', '_pat_'), secret: fake('lywX6dZ5atjY4bLC3XH3TFcscTDh8w') },
      anthropicKey: { prefix: j('s', 'k-ant-', 'api03-'), secret: fake('sx1fG2Vp7Lr-WdXiSVWrJ8MLAC-2fwIvLQJU8FgU') },
      openaiProjectKey: { prefix: j('s', 'k-proj-'), secret: fake('5ybN3FNU513Q7iTVijBtcWJ-c4yz90U00CEkvF8p') },
      openaiLegacyKey: { prefix: j('s', 'k-'), secret: fake('kqfpEg76j70A2c6dzixa') + 'T3BlbkFJ' + fake('tpQgZiAz4BJP6qfTHlBy') },
      openaiKey48: { prefix: j('s', 'k-'), secret: fake('nXKSGTTYMoBb3OiUawkQ5k1drWFDdbGErHbaYtp19BJNr0vT') },
      huggingfaceToken: { prefix: j('hf', '_'), secret: fake('PVgRkI0TCYZsNbnb69tlLOunTocelUoANT') },
      npmToken: { prefix: j('npm', '_'), secret: fake('1AfaIySP80jWP2iI40g0TjHWk0kvx1Se7PsN') },
      dockerPat: { prefix: j('dc', 'kr_', 'pa', 't_'), secret: fake('Ab1Cd2Ef3Gh4Ij5Kl6Mn7') },
      pypiToken: { prefix: j('pypi', '-AgE'), secret: fake('QhjvrsUhcUCGfRZD0ggKjwgR09UBFYUMNa32dOLUOihkUJwXrV8xATHq_vNl') },
      sendgridKey: { prefix: j('S', 'G.'), secret: fake('UyoLcYn_OTP2AVnN8HHo3Q') + '.' + fake('zd0Dzbfr-051hbSf0q2FAkX09yd9Ojua28m2G_SA3hm') },
      jwt: { prefix: 'eyJ', secret: fake('SERoiffMb4bZ') + '.eyJ' + fake('Uj8OA2qbvyc4') + '.' + fake('ekp09zbYOWXMyF_w6XKS') },
      jwtWide: { prefix: 'eyJ', secret: fake('Qm8Zr4Tx') + '.' + fake('Wn6Kd2Vp') + '.' + fake('Hs9Lc3Yb') },
      // WHY the secret has no digit (TRDD-L1I0FP5T): the bare Bearer rule (bearerBare) needs a digit in its value and has no leading \b, so it would hide an Authorization: Bearer value with a digit after these escapes and this entry would stop pinning bearerToken's own defect; a digit-free value of 16+ characters is hidden by bearerToken alone.
      bearerToken: { lead: 'Authorization: Bearer ', prefix: '', secret: fake('lZmCMpd_tO_G_UZDnHUJJs-_URIHab') },
      slackToken: { prefix: j('xo', 'xb-'), secret: fake('5065969875') + '-' + fake('0509749660') + '-' + fake('zDynHn4HnpmBwUjbocXfjj3r') },
      stripeApiKey: { prefix: j('s', 'k_live_'), secret: fake('npxqRcM4BeQSpqu6xYVOvZwx') },
      stripeWebhookSecret: { prefix: j('wh', 'sec_'), secret: fake('7jWBCCK0WmWnOoJwtmqyWce1UStjLA') },
    }
    const contexts: Array<[string, (token: string) => string]> = [
      ['backslash-n', token => `{"m":"line${BS}n${token}"}`],
      ['percent-22', token => `q=%22${token}%22`],
      ['backslash-t', token => `a${BS}t${token}`],
    ]
    // The rules are told apart by their pattern text only: running a shared /g RegExp directly keeps its lastIndex (rules/rule.ts).
    const led = Object.entries(rules)
      .filter(([, rule]) => /^(\\b|\(\?<[!=])/.test(rule.pattern.source))
      .map(([name]) => name)
      .sort()
    expect(led.length).toBe(23)
    expect(Object.keys(tokens).sort().join(',')).toBe(led.join(','))
    for (const name of led) {
      const { lead = '', prefix, secret } = tokens[name]
      const token = lead + prefix + secret
      check(`${name} standalone hidden`, hiddenAs(`see ${token} here`, secret, rules[name].kind))
      for (const [context, frame] of contexts) check(`${name} after ${context} visible`, shown(frame(token), secret))
    }
  })

  test('KNOWN MISS gitlab-session-cookie-under-16-chars: a session cookie cut to 15 characters is not hidden, with 16 characters it is', () => {
    const short = fake('4f8a2c6e1b9d3a7')
    const edge = fake('4f8a2c6e1b9d3a7c')
    expect(short.length).toBe(15)
    expect(edge.length).toBe(16)
    expect(shown(`Cookie: _gitlab_session=${short}`, short)).toBe(true)
    check('16 characters hidden', hiddenAs(`Cookie: _gitlab_session=${edge}`, edge, 'gitlab-session-cookie'))
  })

  test('KNOWN MISS gitlab-session-cookie-value-with-delimiter: the part of a session cookie value after an ampersand is not hidden, a value without one is', () => {
    const head = fake('9a1b2c3d4e5f60718293')
    const tail = fake('a4b5c6d7e8f901234567')
    expect(head.length).toBe(20)
    expect(tail.length).toBe(20)
    expect(shown(`x?_gitlab_session=${head}&${tail}`, tail)).toBe(true)
    check('head hidden', hiddenAs(`x?_gitlab_session=${head}&${tail}`, head, 'gitlab-session-cookie'))
    check('whole value hidden without the ampersand', hiddenAs(`x?_gitlab_session=${head}${tail}`, head + tail, 'gitlab-session-cookie'))
  })

  test('KNOWN MISS gitlab-session-cookie-fields-beyond-span: a session cookie value more than 512 characters from the name, or past a closing brace, is not hidden; within 512 characters it is', () => {
    // The window pass reads 512 characters around the name and stops at ; { }. The filler field is 7 characters plus its text; from the end of the name to the start of the value are 22 characters plus the filler (name first), and from the start of the value to the start of the name 53 plus the filler (value first).
    const apart = (filler: number) => `"x": "${'a'.repeat(filler)}"`
    const farName = fake('c1d2e3f405162738495a6b7c8d9e0f1a')
    const nearName = fake('d2e3f405162738495a6b7c8d9e0f1a2b')
    const farValue = fake('e3f405162738495a6b7c8d9e0f1a2b3c')
    const nearValue = fake('f405162738495a6b7c8d9e0f1a2b3c4d')
    const nested = fake('0516273849a5b6c7d8e9f0a1b2c3d4e5')
    expect(shown(`{"name": "_gitlab_session", ${apart(480)}, "value": "${farName}"}`, farName)).toBe(true)
    check('name first, 440 characters of other fields between, hidden', hiddenAs(`{"name": "_gitlab_session", ${apart(440)}, "value": "${nearName}"}`, nearName, 'gitlab-session-cookie'))
    expect(shown(`{"value": "${farValue}", ${apart(480)}, "name": "_gitlab_session"}`, farValue)).toBe(true)
    check('value first, 440 characters of other fields between, hidden', hiddenAs(`{"value": "${nearValue}", ${apart(440)}, "name": "_gitlab_session"}`, nearValue, 'gitlab-session-cookie'))
    expect(shown(`{"name": "_gitlab_session", "meta": {"a": 1}, "value": "${nested}"}`, nested)).toBe(true)
  })

  test('KNOWN MISS gitlab-session-cookie-double-url-encoded: a session cookie value after a double-URL-encoded equals sign is not hidden, after a single-encoded one it is', () => {
    const value = fake('2b3c4d5e6f708192a3b4c5d6e7f80192')
    expect(value.length).toBe(32)
    expect(shown(`q=_gitlab_session%253D${value}`, value)).toBe(true)
    check('single-encoded hidden', hiddenAs(`q=_gitlab_session%3D${value}`, value, 'gitlab-session-cookie'))
  })

  test('KNOWN MISS gitlab-session-cookie-split-across-line-wrap: a session cookie value broken by a line wrap is hidden only in its first part, an unbroken value is hidden whole', () => {
    const head = fake('3f9a6c1e8b2d4a7f5c0e')
    const tail = fake('91b3d5f7a2c4')
    expect(head.length + tail.length).toBe(32)
    expect(shown(`Cookie: _gitlab_session=${head}\n${tail}`, tail)).toBe(true)
    check('the unbroken value is hidden whole', hiddenAs(`Cookie: _gitlab_session=${head}${tail}`, head + tail, 'gitlab-session-cookie'))
  })

  test('KNOWN MISS gitlab-session-cookie-uppercase-hex: an upper-case 32-hex session cookie value in a keyword-argument form is not hidden, the same value in lower case is', () => {
    const upper = fake('3F9A6C1E8B2D4A7F5C0E91B3D5F7A2C4')
    expect(/^[0-9A-F]{32}$/.test(upper)).toBe(true)
    expect(shown(`create_cookie(name='_gitlab_session', value='${upper}')`, upper)).toBe(true)
    check('the lower-case value is hidden', hiddenAs(`create_cookie(name='_gitlab_session', value='${upper.toLowerCase()}')`, upper.toLowerCase(), 'gitlab-session-cookie'))
  })
})
