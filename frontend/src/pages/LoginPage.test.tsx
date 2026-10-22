import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const authState = vi.hoisted(() => ({
  session: null as { user: { id: string } } | null,
  isConfigured: true,
  signInWithPassword: vi.fn(),
  signUp: vi.fn(),
}));

vi.mock("../auth/AuthProvider", () => ({
  useAuth: () => authState,
}));

import { LoginPage } from "./LoginPage";

afterEach(() => cleanup());

beforeEach(() => {
  authState.session = null;
  authState.isConfigured = true;
  authState.signInWithPassword.mockReset();
  authState.signUp.mockReset();
});

function renderPage() {
  return render(<LoginPage />);
}

describe("LoginPage", () => {
  it("opens on sign in, with only the fields that need it", () => {
    renderPage();

    expect(screen.getByRole("heading", { name: "Sign in." })).toBeTruthy();
    expect(screen.getByLabelText(/email address/i)).toBeTruthy();
    expect(screen.getByLabelText(/^password$/i)).toBeTruthy();
    // The two sign-up-only fields are absent, which is what makes the sign-in
    // card shorter than the sign-up one.
    expect(screen.queryByLabelText(/display name/i)).toBeNull();
    expect(screen.queryByLabelText(/confirm password/i)).toBeNull();
  });

  it("switches to sign up and shows its own fields", () => {
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(screen.getByRole("heading", { name: "Create your account." })).toBeTruthy();
    expect(screen.getByLabelText(/display name/i)).toBeTruthy();
    expect(screen.getByLabelText(/confirm password/i)).toBeTruthy();
    // The sign-in fields stay, because a sign-up needs them too.
    expect(screen.getByLabelText(/email address/i)).toBeTruthy();
  });

  it("marks the active mode, and only the active mode", () => {
    renderPage();

    const signIn = screen.getByRole("button", { name: "Sign in" });
    const create = screen.getByRole("button", { name: "Create" });
    expect(signIn.getAttribute("aria-pressed")).toBe("true");
    expect(create.getAttribute("aria-pressed")).toBe("false");

    fireEvent.click(create);
    expect(signIn.getAttribute("aria-pressed")).toBe("false");
    expect(create.getAttribute("aria-pressed")).toBe("true");
  });

  it("clears the password when the mode changes", () => {
    // Switching from sign in to sign up should not carry a typed password across,
    // and the confirm field starts empty.
    renderPage();

    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: "hunter2hunter2" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    expect((screen.getByLabelText(/^password$/i) as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText(/confirm password/i) as HTMLInputElement).value).toBe("");
  });

  it("signs in with the entered credentials", async () => {
    renderPage();

    fireEvent.change(screen.getByLabelText(/email address/i), { target: { value: "a@b.test" } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: "hunter2hunter2" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in to account/i }));

    await waitFor(() => expect(authState.signInWithPassword).toHaveBeenCalledWith("a@b.test", "hunter2hunter2"));
  });

  it("signs up with a display name", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    fireEvent.change(screen.getByLabelText(/display name/i), { target: { value: "Ada" } });
    fireEvent.change(screen.getByLabelText(/email address/i), { target: { value: "a@b.test" } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: "hunter2hunter2" } });
    fireEvent.change(screen.getByLabelText(/confirm password/i), { target: { value: "hunter2hunter2" } });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => expect(authState.signUp).toHaveBeenCalledWith({
      displayName: "Ada", email: "a@b.test", password: "hunter2hunter2",
    }));
  });

  it("rejects a sign-up whose passwords do not match, before calling the API", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    fireEvent.change(screen.getByLabelText(/display name/i), { target: { value: "Ada" } });
    fireEvent.change(screen.getByLabelText(/email address/i), { target: { value: "a@b.test" } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: "hunter2hunter2" } });
    fireEvent.change(screen.getByLabelText(/confirm password/i), { target: { value: "different1" } });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(authState.signUp).not.toHaveBeenCalled();
  });

  it("explains itself when the auth backend is not configured", () => {
    authState.isConfigured = false;
    renderPage();

    // The form is not rendered at all, because there is nothing to submit to.
    expect(screen.queryByLabelText(/email address/i)).toBeNull();
    expect(screen.getByRole("alert")).toBeTruthy();
  });
});
