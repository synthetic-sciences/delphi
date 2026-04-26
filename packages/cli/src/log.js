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
  "",
  "  ██████╗ ███████╗██╗     ██████╗ ██╗  ██╗██╗",
  "  ██╔══██╗██╔════╝██║     ██╔══██╗██║  ██║██║",
  "  ██║  ██║█████╗  ██║     ██████╔╝███████║██║",
  "  ██║  ██║██╔══╝  ██║     ██╔═══╝ ██╔══██║██║",
  "  ██████╔╝███████╗███████╗██║     ██║  ██║██║",
  "  ╚═════╝ ╚══════╝╚══════╝╚═╝     ╚═╝  ╚═╝╚═╝",
  "",
].join("\n");

const FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

export function banner() {
  // Color each line individually so terminals don't reset color mid-glyph.
  for (const line of ART.split("\n")) {
    console.log(line ? pc.cyan(line) : "");
  }
  console.log(
    pc.dim("  semantic context for AI coding agents") +
      "  " +
      pc.dim(pc.italic("by Synsci"))
  );
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
