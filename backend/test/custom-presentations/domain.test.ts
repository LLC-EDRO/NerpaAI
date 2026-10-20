import test from "node:test";
import assert from "node:assert/strict";
import {evidenceNumbers} from '../../src/custom-presentations/engine/source-numbers.js';

import {type Layout} from '../../src/custom-presentations/engine/domain.js';

import {sandboxArtifactAllowed,receiveSandboxOutput,validateSandboxArtifacts} from '../../src/custom-presentations/engine/sandbox-protocol.js';


import { mkdir, mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
const layout: Layout = {
  id: "slide_1",
  index: 0,
  name: "Метрика",
  usable: true,
  warnings: [],
  charts: [],
  slots: [
    {
      key: "s2",
      text: "99%",
      shapeId: 2,
      role: "body",
      maxChars: 4,
      size: 70,
      x: 10,
      y: 10,
      w: 100,
      h: 80,
    },
  ],
};
const spec = {
  composition: "Метрика",
  fields: [
    {
      key: "s2",
      role: "metric",
      group: "metric",
      intent: "Доля участников",
      action: "replace",
      required: true,
    },
  ],
  charts: [],
};
test("sandbox refuses traversal and incomplete PPTX output", () => {
  assert.equal(sandboxArtifactAllowed("html_export", "../.env"), false);
  assert.equal(sandboxArtifactAllowed("html_export", "presentation.pptx"), true);
  assert.throws(() => validateSandboxArtifacts("html_export", {}, [], 3));
});

test("framed sandbox output handles chunk boundaries and rejects truncated streams", async () => {
  const dir = await mkdtemp(join(tmpdir(), "lab-protocol-test-"));
  try {
    await mkdir(join(dir, "good"));
    const payload = Buffer.from(
      JSON.stringify({ result: { slideCount: 1 } }) +
        "\n" +
        JSON.stringify({ file: "presentation.pptx", size: 3 }) +
        "\n" +
        JSON.stringify({ chunk: Buffer.from("abc").toString("base64") }) +
        "\n" +
        JSON.stringify({ endFile: true }) +
        "\n" +
        JSON.stringify({ done: true }) +
        "\n",
    );
    async function* chunks() {
      for (let i = 0; i < payload.length; i += 7)
        yield payload.subarray(i, i + 7);
    }
    const out = await receiveSandboxOutput(
      chunks(),
      "html_export",
      join(dir, "good"),
    );
    assert.deepEqual(out.files, ["presentation.pptx"]);
    assert.equal(
      await readFile(join(dir, "good/presentation.pptx"), "utf8"),
      "abc",
    );
    async function* broken() {
      yield Buffer.from('{"result":{}}\n');
    }
    await assert.rejects(() => receiveSandboxOutput(broken(), "html_export", dir));
  } finally {
    await rm(dir, { recursive: true });
  }
});
