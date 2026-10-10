import { ApiError, NetworkError } from "./client";

export function describeError(error: unknown): string {
  if (error instanceof ApiError || error instanceof NetworkError) return error.message;
  return "Unexpected error while contacting the API";
}
