/** Allow loopback and RFC 1918 IPv4 hosts for the same-origin analysis server. */
export function isLocalAnalysisHost(hostname: string): boolean {
  if (["localhost", "127.0.0.1", "[::1]"].includes(hostname)) return true;
  if (!/^(?:\d{1,3}\.){3}\d{1,3}$/.test(hostname)) return false;
  const octets = hostname.split(".").map(Number);
  if (octets.some(octet => octet > 255)) return false;
  return octets[0] === 10 ||
    (octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31) ||
    (octets[0] === 192 && octets[1] === 168);
}
