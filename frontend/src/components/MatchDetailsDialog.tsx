import { useEffect, useRef } from "react";
import type { CreatorSnapshot, CorpusKind, MatchRating, ProspectSnapshot, RankedEntry } from "../types";
import { MatchDetailsPanel } from "./MatchDetailsPanel";

export function MatchDetailsDialog({
  kind,
  candidate,
  entry,
  saved,
  saving,
  saveError,
  onSave,
  feedbackRating,
  feedbackSaving,
  feedbackError,
  onFeedback,
  onClose,
}: {
  kind: CorpusKind;
  candidate: CreatorSnapshot | ProspectSnapshot;
  entry: RankedEntry;
  saved: boolean;
  saving: boolean;
  saveError: string | null;
  onSave: () => void;
  feedbackRating: MatchRating | null;
  feedbackSaving: boolean;
  feedbackError: string | null;
  onFeedback: (rating: MatchRating) => void;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const cleanupCloseRef = useRef(false);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    dialog.showModal();
    return () => {
      if (dialog.open) {
        cleanupCloseRef.current = true;
        dialog.close();
      }
    };
  }, []);

  function handleClose() {
    if (cleanupCloseRef.current) {
      cleanupCloseRef.current = false;
      return;
    }
    onClose();
  }

  return (
    <dialog
      ref={dialogRef}
      className="match-profile-dialog"
      aria-labelledby="match-details-title"
      onClose={handleClose}
      onClick={(event) => {
        if (event.target === event.currentTarget) dialogRef.current?.close();
      }}
    >
      <div className="match-profile-dialog-header">
        <span className="eyebrow">Profile details</span>
        <button className="btn btn-ghost" type="button" onClick={() => dialogRef.current?.close()}>
          Close
        </button>
      </div>
      <MatchDetailsPanel
        kind={kind}
        candidate={candidate}
        entry={entry}
        saved={saved}
        saving={saving}
        saveError={saveError}
        onSave={onSave}
        feedbackRating={feedbackRating}
        feedbackSaving={feedbackSaving}
        feedbackError={feedbackError}
        onFeedback={onFeedback}
      />
    </dialog>
  );
}
