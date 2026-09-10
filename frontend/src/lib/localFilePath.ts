export function resolveSelectedLocalPath(file: File, inputValue: string): string | null {
  const localPath = (file as File & { path?: string }).path?.trim();
  if (localPath) {
    return localPath;
  }

  const raw = inputValue.trim();
  if (raw && !raw.toLowerCase().includes("fakepath")) {
    return raw;
  }
  return null;
}
