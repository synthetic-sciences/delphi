// Browser-side API client for the auth service.

const BASE_URL = "/api";

export async function fetchUser(userId) {
  const res = await fetch(`${BASE_URL}/users/${userId}`);
  if (!res.ok) {
    throw new Error(`failed to fetch user: ${res.status}`);
  }
  return res.json();
}

export async function postLogin(username, password) {
  const res = await fetch(`${BASE_URL}/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    throw new Error("login failed");
  }
  return res.json();
}
