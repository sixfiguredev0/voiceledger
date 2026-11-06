let session: Promise<string> | undefined;
export const token = () =>
  (session ??= fetch("/api/v1/session")
    .then(async (r) => {
      if (!r.ok) throw Error("Cannot connect to VoiceLedger");
      return (await r.json()).token as string;
    })
    .catch((error) => {
      session = undefined;
      throw error;
    }));
export async function api<T>(
  path: string,
  options: RequestInit = {},
  retrySession = true,
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("x-voiceledger-token", await token());
  if (options.body && !(options.body instanceof FormData))
    headers.set("content-type", "application/json");
  const r = await fetch("/api/v1" + path, { ...options, headers });
  if (r.status === 401 && retrySession) {
    session = undefined;
    return api(path, options, false);
  }
  if (!r.ok) {
    let value;
    try {
      value = await r.json();
    } catch {
      throw Error(`Request failed (${r.status})`);
    }
    throw Error(
      typeof value.detail === "string"
        ? value.detail
        : JSON.stringify(value.detail),
    );
  }
  return r.json();
}
export const post = <T>(path: string, body: unknown = {}) =>
  api<T>(path, { method: "POST", body: JSON.stringify(body) });
export async function uploadFile(
  project: string,
  file: File,
  onProgress: (value: number) => void,
): Promise<unknown> {
  const auth = await token();
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/v1/projects/${project}/recordings`);
    xhr.setRequestHeader("x-voiceledger-token", auth);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onerror = () => reject(Error("Import connection failed"));
    xhr.onload = () => {
      try {
        const value = JSON.parse(xhr.responseText);
        if (xhr.status >= 400) reject(Error(value.detail ?? "Import failed"));
        else resolve(value);
      } catch {
        reject(Error("Invalid import response"));
      }
    };
    const data = new FormData();
    data.append("file", file);
    xhr.send(data);
  });
}
export async function download(path: string, filename: string) {
  const r = await fetch("/api/v1" + path, {
    headers: { "x-voiceledger-token": await token() },
  });
  if (!r.ok) throw Error("Export failed");
  const url = URL.createObjectURL(await r.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function time(ms: number, full = false) {
  const seconds = Math.floor(Math.max(0, ms) / 1000),
    h = Math.floor(seconds / 3600),
    m = Math.floor((seconds % 3600) / 60),
    s = seconds % 60;
  return h || full
    ? `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}
export function color(value: string | null) {
  let n = 0;
  for (const c of value ?? "unknown") n = (n * 31 + c.charCodeAt(0)) >>> 0;
  return ["#e9bf7a", "#9dc9c0", "#b6b0df", "#c4d497", "#dda5b6", "#9ebddd"][
    n % 6
  ];
}
