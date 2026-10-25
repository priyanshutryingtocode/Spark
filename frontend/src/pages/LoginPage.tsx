import { useState } from "react";
import type { FormEvent } from "react";
import { Link, Navigate } from "react-router-dom";

import { ErrorNote, NOTE_TITLES } from "../components/SystemNote";
import { useAuth } from "../auth/AuthProvider";

type AuthMode = "signin" | "signup";

const minimumPasswordLength = 8;

export function LoginPage({ initialMode = "signin" }: { initialMode?: AuthMode }) {
  const { session, isConfigured, signInWithPassword, signUp } = useAuth();
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (session) return <Navigate to="/creators/search" replace />;

  function changeMode(nextMode: AuthMode) {
    setMode(nextMode);
    setMessage(null);
    setError(null);
    setPassword("");
    setConfirmPassword("");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setMessage(null);
    const normalizedEmail = email.trim();
    if (!normalizedEmail) {
      setError("Enter your email address.");
      return;
    }
    if (password.length < minimumPasswordLength) {
      setError(`Password must be at least ${minimumPasswordLength} characters.`);
      return;
    }
    if (mode === "signup") {
      if (displayName.trim().length < 2) {
        setError("Enter a display name with at least two characters.");
        return;
      }
      if (password !== confirmPassword) {
        setError("Passwords do not match.");
        return;
      }
    }

    setIsSubmitting(true);
    try {
      if (mode === "signup") {
        const hasSession = await signUp({ displayName, email: normalizedEmail, password });
        setMessage(hasSession ? "Account created. You are signed in." : "Account created. Check your email to confirm it.");
      } else {
        await signInWithPassword(normalizedEmail, password);
      }
    } catch (caught) {
      setError(authErrorMessage(caught, mode === "signup" ? "Could not create the account." : "Could not sign in."));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <div className="auth-layout">
        <aside className="auth-story">
          <Link className="auth-brand" to="/" aria-label="Spark home">
            <img src="/logo-mark.png" alt="" width={38} height={38} />
            <span>Spark</span>
          </Link>
          <div className="auth-story-copy">
            <p className="eyebrow">Creator and company intelligence</p>
            <h2>Find the right fit. Know why it fits.</h2>
            <p>Turn a clear brief into a ranked shortlist, with the evidence beside every recommendation.</p>
          </div>
          <span className="auth-story-foot">A considered way to find your next partner.</span>
        </aside>
        <section className="auth-card">
          <div className="auth-card-heading">
            <p className="eyebrow">Your workspace</p>
            <h1>{mode === "signin" ? "Sign in." : "Create your account."}</h1>
            <p className="page-description">
              {mode === "signin" ? "Sign in to continue to your workspace." : "Set up an account to save searches and build shortlists."}
            </p>
          </div>
          {!isConfigured ? (
            <ErrorNote title={NOTE_TITLES.authConfig}>
              Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY in the frontend environment.
            </ErrorNote>
          ) : (
            <>
              <div className="auth-mode-switch" role="group" aria-label="Account access">
                <button className={mode === "signin" ? "auth-mode-button active" : "auth-mode-button"} type="button" aria-pressed={mode === "signin"} onClick={() => changeMode("signin")}>Sign in</button>
                <button className={mode === "signup" ? "auth-mode-button active" : "auth-mode-button"} type="button" aria-pressed={mode === "signup"} onClick={() => changeMode("signup")}>Create</button>
              </div>
              <form className="auth-form" onSubmit={submit}>
                {mode === "signup" && (
                  <label>
                    Display name
                    <input type="text" required minLength={2} maxLength={60} autoComplete="name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="Your name" />
                  </label>
                )}
                <label>
                  Email address
                  <input type="email" required autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" />
                </label>
                <label>
                  Password
                  <input type="password" required minLength={minimumPasswordLength} autoComplete={mode === "signin" ? "current-password" : "new-password"} value={password} onChange={(event) => setPassword(event.target.value)} placeholder="At least 8 characters" />
                </label>
                {mode === "signup" && (
                  <label>
                    Confirm password
                    <input type="password" required minLength={minimumPasswordLength} autoComplete="new-password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} placeholder="Repeat your password" />
                  </label>
                )}
                <button className="btn btn-primary" type="submit" disabled={isSubmitting}>
                  {isSubmitting ? "Working..." : mode === "signin" ? "Sign in to account" : "Create account"}
                </button>
                {message && <p className="auth-message" role="status">{message}</p>}
                {error && <p className="auth-error" role="alert">{error}</p>}
              </form>
            </>
          )}
          <p className="auth-back"><Link to="/">Back to Spark</Link></p>
        </section>
      </div>
    </main>
  );
}

function authErrorMessage(caught: unknown, fallback: string): string {
  if (caught instanceof Error && caught.message.trim()) return caught.message;
  if (typeof caught === "string" && caught.trim()) return caught;
  if (caught && typeof caught === "object" && "message" in caught) {
    const message = (caught as { message?: unknown }).message;
    if (typeof message === "string" && message.trim()) return message;
  }
  return fallback;
}
