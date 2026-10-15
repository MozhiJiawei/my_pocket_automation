/* Run the real browser sources with only their DOM and HTTP boundaries replaced. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function createDocument() {
  const elements = new Map();
  const document = {
    activeElement: null,
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, new Element(id));
      return elements.get(id);
    },
    createElement(tag) { return new Element(tag); },
    createElementNS(_namespace, tag) { return new Element(tag); },
  };
  class Element {
    constructor(tag) {
      this.tag = tag;
      this.children = [];
      this.parentNode = null;
      this.attributes = new Map();
      this.dataset = {};
      this.style = {};
      this.value = '';
      this.checked = false;
      this.pointers = new Set();
      this.classes = new Set();
      this.classList = {
        add: (...names) => names.forEach(name => this.classes.add(name)),
        remove: (...names) => names.forEach(name => this.classes.delete(name)),
        toggle: (name, enabled) => {
          enabled = enabled === undefined ? !this.classes.has(name) : enabled;
          if (enabled) this.classes.add(name); else this.classes.delete(name);
          return enabled;
        },
        contains: name => this.classes.has(name),
      };
    }
    append(...nodes) {
      for (const node of nodes) {
        node.remove();
        node.parentNode = this;
        this.children.push(node);
      }
      if (!this.value && nodes.length) this.value = nodes[0].value || '';
    }
    replaceChildren(...nodes) {
      for (const child of this.children) child.parentNode = null;
      this.children = [];
      this.value = '';
      this.append(...nodes);
    }
    remove() {
      if (this.parentNode) {
        this.parentNode.children = this.parentNode.children.filter(child => child !== this);
        this.parentNode = null;
      }
    }
    setAttribute(name, value) {
      this.attributes.set(name, String(value));
      if (name === 'data-slot') this.dataset.slot = String(value);
      if (name === 'class') this.classes = new Set(String(value).split(/\s+/));
    }
    removeAttribute(name) {
      this.attributes.delete(name);
      if (name === 'data-slot') delete this.dataset.slot;
    }
    cloneNode(deep) {
      const clone = new Element(this.tag);
      for (const [name, value] of this.attributes) clone.setAttribute(name, value);
      clone.classes = new Set(this.classes);
      if (deep) clone.append(...this.children.map(child => child.cloneNode(true)));
      return clone;
    }
    focus() { document.activeElement = this; }
    closest(selector) {
      if (selector === '[data-slot]' && this.dataset.slot !== undefined) return this;
      return this.parentNode?.closest(selector) || null;
    }
    getBoundingClientRect() { return { left: 0, top: 0, width: 200, height: 200 }; }
    setPointerCapture(pointer) { this.pointers.add(pointer); }
    hasPointerCapture(pointer) { return this.pointers.has(pointer); }
    releasePointerCapture(pointer) { this.pointers.delete(pointer); }
  }
  document.getElementById('puzzle-labels').checked = true;
  return document;
}

function createContext(fetch = async () => { throw Error('Unexpected request'); }) {
  const document = createDocument();
  const context = vm.createContext({ document, fetch, structuredClone, Date, setInterval() {} });
  vm.runInContext(fs.readFileSync(path.join(__dirname, 'puzzle.js'), 'utf8'), context);
  return { context, document };
}

const cells = [[146, 556, 438, 926], [448, 556, 740, 926],
  [146, 938, 438, 1308], [448, 938, 740, 1308]];
const page = index => `第${String(index).padStart(2, '0')}页.png`;

function puzzleData(field = 'puzzle_locations', stage = 'pending', pages = 2) {
  return {
    stage, kind: '拼图', topic: '测试题目', token: 'test-token', annotatable: true,
    puzzle: { cells, field },
    images: Array.from({ length: pages }, (_, index) => ({ name: page(index + 1), size: [900, 1600] })),
    initial: { 预期: {} }, suggestions: { 预期: {} },
  };
}

function createEditor(data = puzzleData()) {
  const environment = createContext();
  const snapshots = [];
  let changes = 0;
  const editor = vm.runInContext('new PuzzleEditor({})', environment.context);
  editor.api = route => route + '?id=test';
  editor.beforeChange = () => snapshots.push(editor.snapshot());
  editor.onChange = () => changes++;
  editor.message = () => {};
  editor.initialize(data, data.initial);
  editor.setImage(page(1));
  editor.setDisabled(data.stage === 'confirmed');
  return { ...environment, editor, snapshots, changes: () => changes };
}

function review(environment, checked = true) {
  const check = environment.document.getElementById('puzzle-reviewed');
  check.checked = checked;
  check.onchange({ target: check });
}

function pointer(x, y, pointerId = 7) {
  return { clientX: x, clientY: y, pointerId, button: 0, preventDefault() {} };
}

// Objects produced inside vm have different prototypes; compare serialized values.
const plain = value => JSON.parse(JSON.stringify(value));
const tests = {
  puzzle_all_pages_and_serialization() {
    for (const [field, order] of [['puzzle_locations', [3, 2, 1, 4]], ['puzzle_order', 'CBAD']]) {
      const data = puzzleData(field);
      data.initial = { 预期: { [page(1)]: { [field]: order } } };
      const environment = createEditor(data);
      const { editor } = environment;
      assert.equal(editor.complete, false, 'An AI arrangement must not mark a page reviewed');
      assert.deepEqual(plain(editor.answers()), { 预期: {} });
      review(environment);
      assert.equal(editor.count, 1);
      assert.equal(editor.complete, false, 'One reviewed page must not confirm a two-page item');
      assert.deepEqual(plain(editor.answers()), { 预期: { [page(1)]: { [field]: order } } });
      editor.setImage(page(2));
      review(environment);
      assert.equal(editor.complete, true);
      assert.deepEqual(plain(editor.answers()), { 预期: {
        [page(1)]: { [field]: order },
        [page(2)]: { [field]: field === 'puzzle_order' ? 'ABCD' : [1, 2, 3, 4] },
      } });
    }
  },

  puzzle_swap_and_restore_review() {
    const environment = createEditor();
    const { editor, snapshots, document } = environment;
    review(environment);
    editor.setImage(page(2));
    review(environment);
    editor.setImage(page(1));
    const before = editor.snapshot();
    editor.startDrag(pointer(25, 25));
    editor.moveDrag(pointer(150, 25));
    editor.finishDrag(pointer(150, 25));
    assert.deepEqual(plain(editor.orders[page(1)]), [1, 0, 2, 3]);
    assert.equal(editor.reviewed[page(1)], false, 'Swapping must invalidate this page review');
    assert.equal(editor.reviewed[page(2)], true, 'Swapping must preserve the other page review');
    assert.deepEqual(plain(snapshots.at(-1)), plain(before));
    assert.deepEqual(plain(before.orders[page(1)]), [0, 1, 2, 3], 'Undo snapshots must not alias live orders');
    editor.restore(before);
    editor.render();
    assert.equal(editor.complete, true);
    assert.deepEqual(plain(editor.orders[page(1)]), [0, 1, 2, 3]);
    document.getElementById('puzzle-reset').onclick();
    assert.equal(editor.reviewed[page(1)], false);
    assert.equal(editor.reviewed[page(2)], true);
  },

  puzzle_cancel_and_readonly() {
    const environment = createEditor();
    const { editor, document } = environment;
    const before = editor.snapshot();
    editor.startDrag(pointer(25, 25));
    editor.moveDrag(pointer(220, 25));
    editor.finishDrag(pointer(220, 25));
    assert.deepEqual(plain(editor.snapshot()), plain(before), 'Dropping outside must leave the order unchanged');
    assert.equal(editor.canvas.children.length, 4);
    editor.startDrag(pointer(25, 25));
    editor.setImage(page(2));
    assert.equal(editor.drag, null, 'Switching pages must cancel the drag');
    assert.equal(editor.canvas.hasPointerCapture(7), false);
    editor.finishDrag(pointer(150, 25));
    assert.deepEqual(plain(editor.snapshot()), plain(before));
    editor.startDrag(pointer(25, 25));
    editor.setDisabled(true);
    assert.equal(editor.drag, null, 'Disabling the editor must cancel an active drag');
    assert.equal(editor.canvas.hasPointerCapture(7), false);
    editor.startDrag(pointer(25, 25));
    editor.swap(0, 1);
    review(environment);
    document.getElementById('puzzle-reset').onclick();
    assert.deepEqual(plain(editor.snapshot()), plain(before));
    assert.equal(environment.changes(), 0, 'Readonly interaction must not notify a change');
    const archive = createEditor(puzzleData('puzzle_order', 'confirmed'));
    assert.equal(archive.editor.complete, true);
    assert.equal(archive.document.getElementById('puzzle-reviewed').disabled, true);
    archive.editor.swap(0, 1);
    assert.deepEqual(plain(archive.editor.answers()), { 预期: {
      [page(1)]: { puzzle_order: 'ABCD' }, [page(2)]: { puzzle_order: 'ABCD' },
    } });
  },
};

function inventoryData(stage) {
  const box = [70, 543, 202, 675];
  return {
    stage, kind: '寻物', topic: '测试题目', token: 'test-token', annotatable: true,
    images: [{ name: page(1), size: [900, 1600] }],
    cells: [{ image: page(1), box }],
    strip: { size: [766, 2689], layers: [{ image: page(1), source: [63, 540, 829, 678], destination: [0, 205, 766, 343] }] },
    initial: { 正确: { 测试题目: { [page(1)]: [box] } } }, suggestions: { 正确: { 测试题目: {} } },
  };
}

async function createApp({ kind = '拼图', heights = [1600, 1600], failSecond = false } = {}) {
  const category = `师门/${kind}/测试题目`;
  const a = category + '/A', b = category + '/B';
  const queue = { pending: [a, b].map(id => ({ id, task: '师门', kind, topic: '测试题目', name: id.slice(-1) })), confirmed: [] };
  const requests = [];
  const fetch = url => {
    if (url === '/api/queue') return new Promise(resolve => requests.push(resolve));
    if (url.startsWith('/api/confirm')) return new Promise(() => {});
    const params = new URL(url, 'http://localhost').searchParams, id = params.get('id'), stage = params.get('stage');
    if (failSecond && id === b) return Promise.resolve({ ok: false, json: async () => ({ error: '无效原图' }) });
    const item = kind === '拼图' ? puzzleData('puzzle_locations', stage, 1) : inventoryData(stage);
    return Promise.resolve({ ok: true, json: async () => ({ ...item, id, height: heights[id === a ? 0 : 1], minimum: kind === '拼图' ? 1600 : 2760 }) });
  };
  const environment = createContext(fetch);
  const { context } = environment;
  Object.assign(context, { queueSeed: queue, categorySeed: category, aSeed: a, bSeed: b });
  const source = fs.readFileSync(path.join(__dirname, 'app.js'), 'utf8')
    .replace('refresh().catch(error=>empty(error.message));', '');
  vm.runInContext(source, context);
  await vm.runInContext('queues=queueSeed;category=categorySeed;load(aSeed)', context);
  return {
    ...environment, b,
    run: source => vm.runInContext(source, context),
    respondQueue: () => requests.shift()({ ok: true, json: async () => queue }),
  };
}

tests.queue_refresh_preserves_new_round = async () => {
  const app = await createApp();
  const earlierRefresh = app.run('refresh(currentId)');
  await app.run('load(bSeed)');
  app.respondQueue();
  await earlierRefresh;
  assert.equal(app.run('currentId'), app.b, 'A stale refresh must not restore the old round');
};

tests.queue_refresh_cannot_unlock_confirmation = async () => {
  const app = await createApp();
  review(app);
  assert.equal(app.run('puzzle.complete'), true);
  const earlierRefresh = app.run('refresh(currentId)');
  app.run('confirmCurrent()');
  app.respondQueue();
  await earlierRefresh;
  assert.equal(app.run('confirming'), true);
  assert.equal(app.run('ready'), false, 'A stale refresh must not reactivate an item during its confirmation');
  assert.equal(app.run('puzzle.disabled'), true);
  assert.equal(app.document.getElementById('save').disabled, true);
};

tests.capture_height_updates_with_round_and_preserves_confirmed_answers = async () => {
  const app = await createApp({ kind: '寻物', heights: [2484, 2760] });
  const banner = app.document.getElementById('capture-height');
  assert.equal(banner.hidden, false);
  assert.equal(banner.textContent, '采集高度：2484 / 2760像素（高度不足）');
  assert.deepEqual(app.document.getElementById('round').children.map(option => option.textContent), ['A', 'B']);
  const answer = plain(app.run('documentAnswers()'));
  assert.equal(app.document.getElementById('overlay').children.length, 1);
  await app.run('load(bSeed)');
  assert.equal(banner.hidden, false, 'Completed capture height remains visible');
  assert.equal(banner.textContent, '采集高度：2760 / 2760像素（高度达标）');
  await app.run("queues.confirmed=[queues.pending[0]];stage='confirmed';load(aSeed)");
  assert.equal(banner.textContent, '采集高度：2484 / 2760像素（高度不足）');
  assert.equal(app.document.getElementById('save').hidden, true);
  assert.equal(app.document.getElementById('undo').disabled, true);
  app.document.getElementById('overlay').children[0].onclick();
  assert.deepEqual(plain(app.run('documentAnswers()')), answer, 'Insufficient height must not remove or unlock a confirmed answer');
};

tests.capture_height_hides_on_the_existing_image_open_error = async () => {
  const app = await createApp({ failSecond: true });
  const banner = app.document.getElementById('capture-height');
  assert.equal(banner.textContent, '采集高度：1600 / 1600像素（高度达标）');
  await app.run('load(bSeed)');
  assert.equal(banner.hidden, true);
  assert.equal(app.document.getElementById('status').textContent, '加载失败：无效原图');
  assert.equal(app.document.getElementById('save').disabled, true);
  assert.equal(app.run('ready'), false);
};

(async () => {
  const selected = process.argv.slice(2);
  for (const name of selected.length ? selected : Object.keys(tests)) {
    assert.equal(typeof tests[name], 'function', `Unknown frontend test: ${name}`);
    await tests[name]();
    process.stdout.write(`PASS ${name}\n`);
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
