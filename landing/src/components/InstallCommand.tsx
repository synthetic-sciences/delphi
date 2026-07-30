export function InstallCommand({
  compact = false,
}: {
  compact?: boolean;
}) {
  return (
    <div
      className={`install-command ${
        compact ? "max-w-[360px]" : "max-w-[560px]"
      }`}
      aria-label="Install Delphi with npx"
    >
      <span aria-hidden="true">$</span>
      <code>npx @synsci/delphi</code>
    </div>
  );
}
