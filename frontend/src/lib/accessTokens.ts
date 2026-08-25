export function fragmentCredential(hash: string, names: readonly string[]): string {
  const params = new URLSearchParams(hash.startsWith("#") ? hash.slice(1) : hash);
  for (const name of names) {
    const token = params.get(name)?.trim();
    if (token) return token;
  }
  return "";
}

export function removeCredentialQuery(href: string, names: readonly string[]): string {
  const url = new URL(href);
  for (const name of names) {
    url.searchParams.delete(name);
  }
  return `${url.pathname}${url.search}${url.hash}`;
}
