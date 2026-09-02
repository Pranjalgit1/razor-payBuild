const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface ValidationIssue {
  loc?: Array<string | number>;
  msg?: string;
}

function errorMessage(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const issues = detail
      .filter((item): item is ValidationIssue => typeof item === "object" && item !== null)
      .map((item) => {
        const field = item.loc?.filter((part) => part !== "body").join(".");
        return `${field ? `${field}: ` : ""}${item.msg ?? "Invalid value"}`;
      });
    if (issues.length) return issues.join("; ");
  }
  return `Request failed with status ${status}.`;
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
    throw new ApiError(errorMessage(body?.detail, response.status), response.status);
  }

  return response.json() as Promise<T>;
}
