import pc from "picocolors";

export const log = {
  info: (msg) => console.log(pc.cyan("›"), msg),
  step: (msg) => console.log(pc.bold(pc.cyan("\n→")), pc.bold(msg)),
  success: (msg) => console.log(pc.green("✓"), msg),
  warn: (msg) => console.log(pc.yellow("!"), msg),
  error: (msg) => console.error(pc.red("✗"), msg),
  dim: (msg) => console.log(pc.dim(msg)),
  raw: (msg) => console.log(msg),
};

const ART = [
  "██████╗ ███████╗██╗     ██████╗ ██╗  ██╗██╗",
  "██╔══██╗██╔════╝██║     ██╔══██╗██║  ██║██║",
  "██║  ██║█████╗  ██║     ██████╔╝███████║██║",
  "██║  ██║██╔══╝  ██║     ██╔═══╝ ██╔══██║██║",
  "██████╔╝███████╗███████╗██║     ██║  ██║██║",
  "╚═════╝ ╚══════╝╚══════╝╚═╝     ╚═╝  ╚═╝╚═╝",
];
const ART_WIDTH = 43;

const FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

export function banner() {
  const center = (line, displayWidth = line.length) => {
    const columns = process.stdout.columns || 80;
    return `${" ".repeat(Math.max(0, Math.floor((columns - displayWidth) / 2)))}${line}`;
  };

  // Color each line individually so terminals don't reset color mid-glyph.
  console.log();
  for (const line of ART) {
    console.log(pc.cyan(center(line, ART_WIDTH)));
  }
  console.log(pc.dim(center("semantic context for AI coding agents")));
  console.log();
}

/** Run an async task with a spinner. Returns the task's resolved value. */
export async function spinner(label, task) {
  let i = 0;
  let done = false;
  const tty = process.stdout.isTTY;
  const tick = () => {
    if (done || !tty) return;
    process.stdout.write(`\r${pc.cyan(FRAMES[i++ % FRAMES.length])} ${label}…`);
  };
  if (tty) tick();
  const handle = tty ? setInterval(tick, 80) : null;
  try {
    const result = await task();
    done = true;
    if (handle) clearInterval(handle);
    if (tty) process.stdout.write(`\r${pc.green("✓")} ${label}\n`);
    else console.log(`✓ ${label}`);
    return result;
  } catch (e) {
    done = true;
    if (handle) clearInterval(handle);
    if (tty) process.stdout.write(`\r${pc.red("✗")} ${label}\n`);
    else console.log(`✗ ${label}`);
    throw e;
  }
}
