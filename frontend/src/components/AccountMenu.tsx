import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { User } from "@supabase/supabase-js";

interface AccountMenuProps {
  user: User;
  signOut: () => Promise<void>;
}

interface AccountIdentity {
  displayName: string;
  email: string;
  initials: string;
}

export function AccountMenu({ user, signOut }: AccountMenuProps) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const signOutRef = useRef<HTMLButtonElement>(null);
  const identity = getAccountIdentity(user);

  useEffect(() => {
    if (!open) return;

    function closeOnOutsidePointer(event: PointerEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    }

    function closeOnEscape(event: KeyboardEvent) {
      // Listening on document, not on the popover: Escape has to close this
      // wherever focus happens to be, including on the trigger.
      if (event.key === "Escape") setOpen(false);
    }

    document.addEventListener("pointerdown", closeOnOutsidePointer);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  const wasOpenRef = useRef(false);
  useEffect(() => {
    if (open) {
      // Opening a popover without moving focus into it leaves a keyboard user
      // tabbing blind through the page behind it. preventScroll because the
      // panel is anchored under the trigger: without it, opening the menu
      // scrolled the page to bring the button into view.
      wasOpenRef.current = true;
      signOutRef.current?.focus({ preventScroll: true });
      return;
    }
    // Closing returns focus to the trigger, so the user is not dropped at the
    // top of the document. Guarded on having been open: this effect also runs
    // on mount, and the unguarded version stole focus to the account button
    // every time the page loaded -- including straight after the skip link,
    // which is the one place focus must not be moved from.
    //
    // preventScroll for the same reason the sign-out focus above has it: the
    // trigger is in the topbar, which is static on a phone and scrolls away,
    // so focusing it would pull the page back up to the bar.
    if (wasOpenRef.current) {
      wasOpenRef.current = false;
      triggerRef.current?.focus({ preventScroll: true });
    }
  }, [open]);

  async function handleSignOut() {
    setSigningOut(true);
    setError(null);
    try {
      await signOut();
      navigate("/", { replace: true });
    } catch {
      setError("Could not sign out. Please try again.");
      setSigningOut(false);
    }
  }

  return (
    <div className="account-menu-root" ref={rootRef}>
      <button
        ref={triggerRef}
        className={open ? "account-trigger open" : "account-trigger"}
        type="button"
        aria-expanded={open}
        aria-controls={open ? "account-popover" : undefined}
        aria-label={open ? "Close account menu" : "Open account menu"}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="account-avatar" aria-hidden="true">{identity.initials}</span>
        <span className="account-trigger-name">{identity.displayName}</span>
      </button>
      {open && (
        /* A disclosure, not a menu. role="menu" was claiming a widget pattern
           its contents did not follow -- an identity header, a rule, and a live
           error region are not menu items -- and with one action it bought
           nothing over aria-expanded. */
        <div className="account-menu" id="account-popover" role="group" aria-label="Account">
          <div className="account-menu-header">
            <span className="account-avatar account-avatar-large" aria-hidden="true">{identity.initials}</span>
            <div className="account-menu-identity">
              <strong>{identity.displayName}</strong>
              <span>{identity.email}</span>
            </div>
          </div>
          <div className="account-menu-rule" aria-hidden="true" />
          <button ref={signOutRef} className="account-menu-action" type="button" disabled={signingOut} onClick={() => void handleSignOut()}>
            {signingOut ? "Signing out..." : "Sign out"}
          </button>
          {error && <p className="account-menu-error" role="alert">{error}</p>}
        </div>
      )}
    </div>
  );
}

function getAccountIdentity(user: User): AccountIdentity {
  const metadataName = user.user_metadata?.display_name;
  const email = typeof user.email === "string" && user.email.trim() ? user.email.trim() : "Signed in";
  const displayName = typeof metadataName === "string" && metadataName.trim()
    ? metadataName.trim()
    : email.split("@")[0] || "Account";
  return { displayName, email, initials: getInitials(displayName, email) };
}

export function getInitials(displayName: string, email: string): string {
  const words = displayName.trim().split(/\s+/).filter(Boolean);
  if (words.length > 1) {
    return `${words[0][0]}${words[words.length - 1][0]}`.toUpperCase();
  }
  const source = words[0] ?? email.split("@")[0] ?? "Account";
  return source.replace(/[^a-z0-9]/gi, "").slice(0, 2).toUpperCase() || "AC";
}
