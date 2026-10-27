// 构建期为 color-mix() 生成静态回退色（NFR-007：iOS Safari 16.0/16.1 不支持 color-mix，Safari 16.2 起支持）。
// 设计令牌只有一套浅色主题，按 tokens.css 的取值预先算出混合结果：
//   普通属性：在原声明前插入回退声明，新浏览器仍以 color-mix 为准；
//   自定义属性（--xxx）：不做语法校验、后写者覆盖，不能就地回退；改为在 @supports not (color-mix) 中重定义为预计算值。
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { Plugin } from "vite";

type RGBA = [number, number, number, number];

function hex(h: string): RGBA {
  const v = h.replace("#", "");
  const n = v.length === 3 ? v.split("").map((c) => c + c).join("") : v;
  return [parseInt(n.slice(0, 2), 16), parseInt(n.slice(2, 4), 16), parseInt(n.slice(4, 6), 16), 1];
}

function tokens(file: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const m of readFileSync(file, "utf8").matchAll(/(--[\w-]+)\s*:\s*(#[0-9a-fA-F]{3,6})\s*;/g)) out[m[1]] = m[2];
  return out;
}

function color(expr: string, t: Record<string, string>): RGBA | null {
  const s = expr.trim();
  if (s === "transparent") return [0, 0, 0, 0];
  if (s === "black") return [0, 0, 0, 1];
  if (s === "white") return [255, 255, 255, 1];
  if (s.startsWith("#")) return hex(s);
  const v = s.match(/^var\((--[\w-]+)\)$/);
  return v && t[v[1]] ? hex(t[v[1]]) : null;
}

function mix(args: string, t: Record<string, string>): string | null {
  const parts = args.split(",").map((x) => x.trim());
  if (parts.length !== 3 || !/^in \w+$/.test(parts[0])) return null;
  const side = (p: string) => {
    const m = p.match(/^(.*?)(?:\s+(\d+(?:\.\d+)?)%)?$/)!;
    return { c: color(m[1], t), p: m[2] === undefined ? null : Number(m[2]) / 100 };
  };
  const a = side(parts[1]);
  const b = side(parts[2]);
  if (!a.c || !b.c) return null;
  const pa = a.p ?? (b.p === null ? 0.5 : 1 - b.p);
  const pb = 1 - pa;
  // 与透明色混合即按比例降低不透明度；其余按通道线性插值（与 oklab 结果相近，仅作旧浏览器回退）
  const alpha = a.c[3] * pa + b.c[3] * pb;
  if (alpha === 0) return "transparent";
  const ch = (i: number) => Math.round((a.c![i] * a.c![3] * pa + b.c![i] * b.c![3] * pb) / alpha);
  return `rgba(${ch(0)},${ch(1)},${ch(2)},${+alpha.toFixed(3)})`;
}

function resolve(value: string, t: Record<string, string>): string | null {
  let ok = true;
  const out = value.replace(/color-mix\(([^()]*(?:\([^()]*\)[^()]*)*)\)/g, (_, args: string) => {
    const r = mix(args, t);
    if (r === null) ok = false;
    return r ?? "";
  });
  return ok ? out : null;
}

export function colorMixFallback(tokensFile: string): Plugin {
  return {
    name: "jh-color-mix-fallback",
    apply: "build",
    // 在产物写盘后处理：CSS 压缩会合并同名重复声明，提前插入的回退会被去掉
    writeBundle(opts, bundle) {
      const t = tokens(tokensFile);
      for (const asset of Object.values(bundle)) {
        if (asset.type !== "asset" || !asset.fileName.endsWith(".css")) continue;
        const file = join(opts.dir || "dist", asset.fileName);
        const css = readFileSync(file, "utf8");
        const customs: string[] = [];
        const out = css.replace(/([{;])\s*((?:--)?[\w-]+)\s*:([^;{}]*color-mix\([^;{}]*)(?=[;}])/g, (all, lead: string, prop: string, value: string) => {
          const fb = resolve(value, t);
          if (fb === null) return all; // currentColor 等无法静态计算：保持原样（旧浏览器仅缺少这一处着色）
          if (prop.startsWith("--")) {
            customs.push(`${prop}:${fb}`);
            return all;
          }
          return `${lead}${prop}:${fb};${prop}:${value}`;
        });
        writeFileSync(file, out + (customs.length ? `@supports not (color:color-mix(in srgb,red,blue)){:root{${customs.join(";")}}}` : ""));
      }
    },
  };
}
