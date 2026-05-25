import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { FIELD_PHOTO_TAGS, type FieldPhoto, type FieldPhotoTag } from "./types";

interface Props {
  areaCode: string;
  placed: FieldPhoto[];
  pending: FieldPhoto[];
  selectedPendingId: number | null;
  /** True when "click map to place this photo" mode is armed; the map's
   *  next click should call onMapClickArmed with lon/lat (handled by App). */
  placementArmed: boolean;
  onPickPendingForPlacement: (photoId: number | null) => void;
  onClose: () => void;
  onChanged: () => void;
  onOpenLightbox: (photo: FieldPhoto) => void;
}

/** Side-panel UI for the photo layer: upload, pending-placement tray, and the
 *  list of placed photos with quick filters. The actual map markers + clicks
 *  are owned by MapView; this panel only manages metadata. */
export default function PhotoPanel({
  areaCode,
  placed,
  pending,
  selectedPendingId,
  placementArmed,
  onPickPendingForPlacement,
  onClose,
  onChanged,
  onOpenLightbox,
}: Props) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{ done: number; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tagFilter, setTagFilter] = useState<FieldPhotoTag | null>(null);

  const filteredPlaced = useMemo(() => {
    if (!tagFilter) return placed;
    return placed.filter((p) => p.tags.includes(tagFilter));
  }, [placed, tagFilter]);

  async function onFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    setError(null);
    setUploading(true);
    setUploadProgress({ done: 0, total: files.length });
    let done = 0;
    let firstError: string | null = null;
    for (const f of Array.from(files)) {
      try {
        await api.uploadPhoto(areaCode, f);
      } catch (e) {
        if (!firstError) firstError = (e as Error)?.message ?? String(e);
      }
      done += 1;
      setUploadProgress({ done, total: files.length });
    }
    setUploading(false);
    setUploadProgress(null);
    if (firstError) setError(firstError);
    onChanged();
  }

  return (
    <div className="site-card" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <h3 style={{ margin: 0 }}>Bilder</h3>
        <div style={{ flex: 1 }} />
        <button onClick={onClose} title="Lukk bilder-panelet">✕</button>
      </div>

      <div>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/heic,image/heif,image/jpeg,image/png,.heic,.heif,.jpg,.jpeg,.png"
          multiple
          style={{ display: "none" }}
          onChange={(e) => { onFiles(e.target.files); if (fileInputRef.current) fileInputRef.current.value = ""; }}
        />
        <button
          className="primary"
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
        >
          {uploading
            ? `Laster opp ${uploadProgress?.done ?? 0}/${uploadProgress?.total ?? 0}…`
            : "+ Last opp bilder"}
        </button>
      </div>

      {error && <div style={{ color: "#c43d3d", fontSize: 12 }}>Feil: {error}</div>}

      {pending.length > 0 && (
        <PendingTray
          pending={pending}
          selectedId={selectedPendingId}
          armed={placementArmed}
          onPickForPlacement={onPickPendingForPlacement}
          onChanged={onChanged}
          onOpenLightbox={onOpenLightbox}
        />
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", marginTop: 4 }}>
        <span style={{ fontSize: 11, color: "#666" }}>Filter:</span>
        <TagChip label="alle" active={tagFilter === null} onClick={() => setTagFilter(null)} />
        {FIELD_PHOTO_TAGS.map((t) => (
          <TagChip key={t} label={t} active={tagFilter === t} onClick={() => setTagFilter(t)} />
        ))}
      </div>

      <div style={{ fontSize: 12, color: "#666" }}>
        {filteredPlaced.length} av {placed.length} plassert
        {pending.length > 0 ? ` · ${pending.length} venter på plassering` : ""}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 4 }}>
        {filteredPlaced.map((p) => (
          <button
            key={p.id}
            onClick={() => onOpenLightbox(p)}
            title={p.caption || `Tatt ${p.taken_at ?? "ukjent"}`}
            style={{
              padding: 0, border: "1px solid #ddd", borderRadius: 3, overflow: "hidden",
              cursor: "pointer", background: "white", aspectRatio: "1 / 1",
            }}
          >
            <img src={p.thumb_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
          </button>
        ))}
      </div>
    </div>
  );
}

function PendingTray({
  pending, selectedId, armed, onPickForPlacement, onChanged, onOpenLightbox,
}: {
  pending: FieldPhoto[];
  selectedId: number | null;
  armed: boolean;
  onPickForPlacement: (photoId: number | null) => void;
  onChanged: () => void;
  onOpenLightbox: (photo: FieldPhoto) => void;
}) {
  return (
    <div style={{ background: "#fff4d0", border: "1px solid #e0c060", borderRadius: 4, padding: 8 }}>
      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>
        Venter på plassering ({pending.length})
      </div>
      <div style={{ fontSize: 11, color: "#5b4400", marginBottom: 6 }}>
        Bilder uten GPS. Velg ett under og klikk på kartet for å plassere det.
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 4 }}>
        {pending.map((p) => {
          const isSelected = p.id === selectedId;
          return (
            <div key={p.id} style={{ position: "relative" }}>
              <button
                onClick={() => onPickForPlacement(isSelected ? null : p.id)}
                title={isSelected
                  ? (armed ? "Klikk på kartet for å plassere" : "Klikk for å avbryte")
                  : "Velg, og klikk så på kartet"}
                style={{
                  padding: 0, width: "100%", aspectRatio: "1 / 1", cursor: "pointer",
                  border: isSelected ? "3px solid #1a7fc4" : "1px solid #aaa",
                  borderRadius: 3, overflow: "hidden", background: "white",
                }}
              >
                <img src={p.thumb_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
              </button>
              <button
                onClick={() => onOpenLightbox(p)}
                title="Vis bilde"
                style={{
                  position: "absolute", top: 2, left: 2, padding: "0 4px",
                  fontSize: 10, lineHeight: "16px", height: 16,
                  background: "rgba(255,255,255,0.85)", border: "none",
                  borderRadius: 2, cursor: "pointer",
                }}
              >
                ⤢
              </button>
              <button
                onClick={async () => {
                  if (!confirm("Slett dette bildet?")) return;
                  await api.deletePhoto(p.id);
                  onChanged();
                }}
                title="Slett"
                style={{
                  position: "absolute", top: 2, right: 2, padding: "0 4px",
                  fontSize: 10, lineHeight: "16px", height: 16,
                  background: "rgba(255,255,255,0.85)", border: "none",
                  borderRadius: 2, cursor: "pointer",
                }}
              >
                ✕
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TagChip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "2px 8px", fontSize: 11, cursor: "pointer", borderRadius: 12,
        border: active ? "1px solid #1a7fc4" : "1px solid #ccc",
        background: active ? "#eaf3fc" : "white",
        color: active ? "#1a7fc4" : "#333",
      }}
    >
      {label}
    </button>
  );
}

// -----------------------------------------------------------------------------

interface LightboxProps {
  photo: FieldPhoto;
  onClose: () => void;
  onChanged: () => void;
}

export function PhotoLightbox({ photo, onClose, onChanged }: LightboxProps) {
  const [caption, setCaption] = useState(photo.caption ?? "");
  const [tags, setTags] = useState<FieldPhotoTag[]>(photo.tags);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setCaption(photo.caption ?? ""); setTags(photo.tags); }, [photo.id, photo.caption, photo.tags]);

  function toggleTag(t: FieldPhotoTag) {
    setTags((cur) => (cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t]));
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api.patchPhoto(photo.id, {
        caption: caption.trim() === "" ? null : caption.trim(),
        tags,
      });
      onChanged();
      onClose();
    } catch (e) {
      setError((e as Error)?.message ?? String(e));
    } finally {
      setBusy(false);
    }
  }

  async function doDelete() {
    if (!confirm("Slett dette bildet?")) return;
    setBusy(true);
    try {
      await api.deletePhoto(photo.id);
      onChanged();
      onClose();
    } catch (e) {
      setError((e as Error)?.message ?? String(e));
      setBusy(false);
    }
  }

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)",
        display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "white", borderRadius: 6, padding: 12,
          width: "min(880px, 92vw)", maxHeight: "92vh", overflow: "auto",
          display: "grid", gridTemplateColumns: "1fr 280px", gap: 12,
        }}
      >
        <div style={{ background: "#000", borderRadius: 4, overflow: "hidden", display: "flex", alignItems: "center", justifyContent: "center", minHeight: 360 }}>
          <img
            src={photo.display_url}
            alt={photo.caption || ""}
            style={{ maxWidth: "100%", maxHeight: "80vh", display: "block" }}
          />
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 8, fontSize: 12 }}>
          <div style={{ display: "flex" }}>
            <strong style={{ flex: 1 }}>Bilde #{photo.id}</strong>
            <button onClick={onClose}>Lukk</button>
          </div>

          <div style={{ color: "#666" }}>
            {photo.taken_at ? <>Tatt: {new Date(photo.taken_at).toLocaleString("no")}<br /></> : null}
            Lastet opp: {photo.uploaded_at ? new Date(photo.uploaded_at).toLocaleString("no") : "—"}
            {photo.lon != null && photo.lat != null
              ? <><br />Posisjon: {photo.lat.toFixed(5)}, {photo.lon.toFixed(5)}</>
              : <><br /><em>Ikke plassert</em></>}
            {photo.exif_heading_deg != null
              ? <><br />Kameraretning: {photo.exif_heading_deg}°</>
              : null}
          </div>

          <label>
            Bildetekst
            <textarea
              value={caption}
              onChange={(e) => setCaption(e.target.value)}
              rows={3}
              style={{ width: "100%", boxSizing: "border-box", marginTop: 2 }}
            />
          </label>

          <div>
            <div style={{ marginBottom: 4 }}>Tagger</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {FIELD_PHOTO_TAGS.map((t) => (
                <TagChip key={t} label={t} active={tags.includes(t)} onClick={() => toggleTag(t)} />
              ))}
            </div>
          </div>

          {error && <div style={{ color: "#c43d3d" }}>Feil: {error}</div>}

          <div style={{ display: "flex", gap: 6, marginTop: "auto" }}>
            <button className="primary" disabled={busy} onClick={save}>Lagre</button>
            <div style={{ flex: 1 }} />
            <button className="danger" disabled={busy} onClick={doDelete}>Slett</button>
          </div>

          <a href={photo.original_url} target="_blank" rel="noreferrer" style={{ fontSize: 11 }}>
            Last ned original
          </a>
        </div>
      </div>
    </div>
  );
}
