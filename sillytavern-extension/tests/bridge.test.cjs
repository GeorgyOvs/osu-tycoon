const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function bridge(generateQuietPrompt) {
    const context = { extensionSettings: {}, generateQuietPrompt };
    const sandbox = vm.createContext({
        SillyTavern: { getContext: () => context },
        jQuery: () => {}, structuredClone, console: { warn() {} },
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../osu-tycoon/index.js'), 'utf8'), sandbox);
    return sandbox;
}

test('a rejected response schema retries once without a schema', async () => {
    const calls = [];
    const app = bridge(async (args) => {
        calls.push(args);
        if (args.jsonSchema) throw new Error('400 Invalid JSON payload: response_schema');
        return '```json\n{"comments":[{"author":"User","content":"gz"}]}\n```';
    });
    const result = await app.generateJson('prompt', { type: 'object' }, 'comments');
    assert.equal(result.comments[0].content, 'gz');
    assert.equal(calls.length, 2);
    assert.ok(calls[0].jsonSchema);
    assert.equal(calls[1].jsonSchema, undefined);
});

test('a valid structured response does not issue a second request', async () => {
    let calls = 0;
    const app = bridge(async () => { calls++; return '{"lines":[{"author":"User","content":"hi"}]}'; });
    assert.equal((await app.generateJson('prompt', {}, 'lines')).lines[0].content, 'hi');
    assert.equal(calls, 1);
});

test('cancelling a request does not start a fallback generation', async () => {
    let calls = 0;
    const app = bridge(async () => {
        calls++;
        const error = new Error('Cancelled');
        error.name = 'AbortError';
        throw error;
    });
    await assert.rejects(app.generateJson('prompt', {}, 'comments'), { name: 'AbortError' });
    assert.equal(calls, 1);
});
