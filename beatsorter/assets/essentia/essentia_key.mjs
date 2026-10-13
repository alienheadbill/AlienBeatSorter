// Essentia's KeyExtractor (essentia.js 0.1.3, the official WebAssembly build
// of Essentia, AGPL-3.0, Music Technology Group - Universitat Pompeu Fabra).
// Beat Sorter runs this with deno because Essentia has no Windows install
// for Python. Protocol: read one path per line on stdin (raw mono float32
// PCM at 44.1 kHz), write one JSON line per path on stdout.
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import process from "node:process";
import readline from "node:readline";

const require = createRequire(import.meta.url);
const wasmMod = require("./essentia-wasm.umd.js");
const EssentiaWASM = wasmMod.EssentiaWASM || wasmMod;
const Essentia = require("./essentia.js-core.umd.js");
await new Promise((ok) => {
  if (EssentiaWASM.calledRun) ok(); else EssentiaWASM.onRuntimeInitialized = ok;
});
const ess = new Essentia(EssentiaWASM);

function analyze(path) {
  const buf = readFileSync(path);
  const pcm = new Float32Array(buf.buffer, buf.byteOffset, Math.floor(buf.byteLength / 4));
  const out = {};
  for (const profile of ["edma", "krumhansl"]) {
    const v = ess.arrayToVector(pcm);
    try {
      // Essentia's KeyExtractor defaults, with the chosen profile
      const r = ess.KeyExtractor(v, true, 4096, 4096, 12, 3500, 60, 25, 0.2, profile,
                                 44100, 0.0001, 440, "cosine", "hann");
      out[profile] = `${r.key} ${r.scale}`;
      out[profile + "_strength"] = r.strength;
    } finally {
      v.delete();
    }
  }
  return out;
}

console.log(JSON.stringify({ ready: true, version: ess.version }));
const rl = readline.createInterface({ input: process.stdin, terminal: false });
for await (const line of rl) {
  const path = line.trim();
  if (!path) continue;
  let res;
  try { res = analyze(path); } catch (e) { res = { error: String(e) }; }
  console.log(JSON.stringify(res));
}
