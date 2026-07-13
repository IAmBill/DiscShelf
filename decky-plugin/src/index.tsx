import {
  Button,
  ButtonItem,
  ConfirmModal,
  Dropdown,
  Field,
  Focusable,
  ModalRoot,
  Navigation,
  PanelSection,
  PanelSectionRow,
  SliderField,
  Spinner,
  staticClasses,
  TextField,
  ToggleField,
  showModal,
} from "@decky/ui";
import {
  callable,
  definePlugin,
  FileSelectionType,
  openFilePicker,
  toaster,
} from "@decky/api";
import { ReactNode, useCallback, useEffect, useRef, useState } from "react";
import {
  FaCompactDisc,
  FaArrowDown,
  FaArrowUp,
  FaFloppyDisk,
  FaFolderOpen,
  FaPen,
  FaPlay,
  FaPlus,
  FaRotate,
  FaStop,
  FaTrash,
  FaVolumeHigh,
  FaXmark,
} from "react-icons/fa6";

type RuntimeStatus = {
  available: boolean;
  path: string | null;
  version: string | null;
  source: "installed" | "development" | null;
  error: string | null;
};

type ManifestSummary = {
  path: string;
  title: string;
  discCount: number;
  layout: string;
  valid: boolean;
  error: string | null;
};

type ScanResult = {
  manifests: ManifestSummary[];
  roots: string[];
};

type LaunchResult = {
  ok: boolean;
  pid: number | null;
  error: string | null;
};

type ManifestSettings = {
  path: string;
  title: string;
  preset: string;
  columns: number;
  rows: number;
  backgroundImage: string;
  backgroundDim: number;
  musicPath: string;
  musicVolume: number;
  musicLoop: boolean;
  discs: DiscSettings[];
};

type AnimationSettings = {
  type: "none" | "spin" | "wiggle";
  delay: number;
  revolutionsPerMinute: number;
  angle: number;
  distance: number;
  period: number;
};

type DiscSettings = {
  label: string;
  path: string;
  artwork: string;
  animation: AnimationSettings;
};

type SettingsResult = {
  ok: boolean;
  settings: ManifestSettings | null;
  error: string | null;
};

type ActionResult = { ok: boolean; error: string | null };
type ImagePreviewResult = { ok: boolean; dataUrl: string | null; error: string | null };

const layoutOptions = [
  { data: "list", label: "List" },
  { data: "showcase", label: "Showcase" },
  { data: "strip", label: "Strip" },
  { data: "compact", label: "Compact" },
  { data: "wide-grid", label: "Wide grid" },
];

const animationOptions = [
  { data: "none", label: "None" },
  { data: "spin", label: "Spin" },
  { data: "wiggle", label: "Wiggle" },
];

const newDisc = (number: number): DiscSettings => ({
  label: `Disc ${number}`,
  path: "",
  artwork: "",
  animation: {
    type: "none",
    delay: 2.5,
    revolutionsPerMinute: 12,
    angle: 30,
    distance: 10,
    period: 1.8,
  },
});

const layoutDefaults: Record<string, { columns: number; rows: number }> = {
  list: { columns: 1, rows: 4 },
  showcase: { columns: 1, rows: 1 },
  strip: { columns: 4, rows: 1 },
  compact: { columns: 2, rows: 2 },
  "wide-grid": { columns: 3, rows: 2 },
};

const getRuntimeStatus = callable<[], RuntimeStatus>("get_runtime_status");
const scanManifests = callable<[], ScanResult>("scan_manifests");
const launchManifest = callable<[path: string], LaunchResult>("launch_manifest");
const getManifestSettings = callable<[path: string], SettingsResult>("get_manifest_settings");
const updateManifestSettings = callable<
  [path: string, settings: ManifestSettings],
  SettingsResult
>("update_manifest_settings");
const previewMusic = callable<
  [manifestPath: string, musicPath: string, volume: number],
  ActionResult
>("preview_music");
const stopMusicPreview = callable<[], ActionResult>("stop_music_preview");
const getImagePreview = callable<
  [manifestPath: string, imagePath: string],
  ImagePreviewResult
>("get_image_preview");

function pickerStart(path: string): string {
  if (!path) return "/home/bazzite";
  const separator = path.lastIndexOf("/");
  return separator > 0 ? path.slice(0, separator) : "/home/bazzite";
}

type ManifestEditorProps = {
  initial: ManifestSettings;
  onClose: () => void;
  onSaved: () => Promise<void>;
};

function ArtworkThumbnail({ manifestPath, imagePath, wide = false, dim = 0, animation, previewing = false }: {
  manifestPath: string;
  imagePath: string;
  wide?: boolean;
  dim?: number;
  animation?: AnimationSettings;
  previewing?: boolean;
}) {
  const [dataUrl, setDataUrl] = useState<string | null>(null);
  const artworkRef = useRef<HTMLImageElement>(null);

  useEffect(() => {
    let active = true;
    setDataUrl(null);
    if (!imagePath) return () => { active = false; };
    void getImagePreview(manifestPath, imagePath).then((result) => {
      if (active && result.ok) setDataUrl(result.dataUrl);
    });
    return () => { active = false; };
  }, [manifestPath, imagePath]);

  useEffect(() => {
    if (!previewing || !animation || animation.type === "none" || !artworkRef.current) return;
    const element = artworkRef.current;
    element.getAnimations().forEach((item) => item.cancel());
    const wiggleFrames = Array.from({ length: 33 }, (_item, index) => {
      const phase = index * Math.PI * 2 / 32;
      return {
        offset: index / 32,
        transform: `translateY(${animation.distance * Math.sin(phase * 2)}px) rotate(${animation.angle * Math.sin(phase)}deg)`,
      };
    });
    const playback = animation.type === "spin"
      ? element.animate(
          [{ transform: "rotate(0deg)" }, { transform: "rotate(360deg)" }],
          {
            duration: Math.max(500, 60000 / animation.revolutionsPerMinute),
            iterations: Infinity,
            easing: "linear",
          },
        )
      : element.animate(
          wiggleFrames,
          { duration: Math.max(100, animation.period * 1000), iterations: Infinity, easing: "linear" },
        );
    return () => playback.cancel();
  }, [animation, previewing]);

  const width = wide ? 220 : 144;
  const height = wide ? 124 : 144;
  const stagePadding = wide ? 0 : 24;
  return (
    <div style={{ boxSizing: "content-box", width, height, padding: stagePadding, flex: `0 0 ${width + stagePadding * 2}px`, display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden" }}>
      <div style={{ position: "relative", width, height, borderRadius: 4, overflow: wide ? "hidden" : "visible" }}>
        {dataUrl ? (
          <img ref={artworkRef} src={dataUrl} style={{ width: "100%", height: "100%", objectFit: "contain" }} />
        ) : (
          <div style={{ display: "flex", width: "100%", height: "100%", alignItems: "center", justifyContent: "center", opacity: 0.6 }}>No preview</div>
        )}
        {dim > 0 && <div style={{ position: "absolute", inset: 0, background: `rgba(0, 0, 0, ${dim})`, pointerEvents: "none" }} />}
      </div>
    </div>
  );
}

function ModalActionButton({ children, disabled = false, onPress }: {
  children: ReactNode;
  disabled?: boolean;
  onPress: () => void;
}) {
  const [highlighted, setHighlighted] = useState(false);
  const lastActivation = useRef(0);
  const activate = () => {
    if (disabled) return;
    const now = Date.now();
    if (now - lastActivation.current < 150) return;
    lastActivation.current = now;
    onPress();
  };
  return (
    <Focusable
      onActivate={(event) => { event.stopPropagation(); activate(); }}
      onClick={(event) => { event.stopPropagation(); activate(); }}
      onFocus={() => setHighlighted(true)}
      onBlur={() => setHighlighted(false)}
      onMouseEnter={() => setHighlighted(true)}
      onMouseLeave={() => setHighlighted(false)}
      style={{
        boxSizing: "border-box",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        minHeight: 44,
        padding: "8px 14px",
        borderRadius: 3,
        color: disabled ? "rgba(255,255,255,0.35)" : "white",
        background: highlighted && !disabled ? "#1a9fff" : "rgba(255,255,255,0.10)",
        opacity: disabled ? 0.55 : 1,
        cursor: disabled ? "default" : "pointer",
        transition: "background 120ms ease",
      }}
    >
      {children}
    </Focusable>
  );
}

function SettingsGroup({ children }: { children: ReactNode }) {
  return (
    <Focusable
      flow-children="down"
      style={{
        boxSizing: "border-box",
        display: "flex",
        flexDirection: "column",
        gap: 12,
        width: "100%",
        padding: 16,
        borderRadius: 4,
        background: "rgba(255,255,255,0.09)",
      }}
    >
      {children}
    </Focusable>
  );
}

function ArtworkPicker({ manifestPath, imagePath, wide = false, dim = 0, animation, previewing, label, onBrowse, onClear }: {
  manifestPath: string;
  imagePath: string;
  wide?: boolean;
  dim?: number;
  animation?: AnimationSettings;
  previewing?: boolean;
  label: string;
  onBrowse: () => void;
  onClear: () => void;
}) {
  return (
    <Focusable flow-children="right" style={{ display: "flex", alignItems: "stretch", gap: 14, width: "100%", minHeight: wide ? 140 : 160 }}>
      <ArtworkThumbnail manifestPath={manifestPath} imagePath={imagePath} wide={wide} dim={dim} animation={animation} previewing={previewing} />
      <Focusable flow-children="down" style={{ display: "flex", flex: 1, minWidth: 0, flexDirection: "column", justifyContent: "center", gap: 8 }}>
        <div style={{ fontWeight: 600 }}>{label}</div>
        <div style={{ opacity: 0.7, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{imagePath || "No image selected"}</div>
        <ModalActionButton onPress={onBrowse}><FaFolderOpen style={{ marginRight: 8 }} /> Select Artwork</ModalActionButton>
        {imagePath && <ModalActionButton onPress={onClear}><FaXmark style={{ marginRight: 8 }} /> Remove Artwork</ModalActionButton>}
      </Focusable>
    </Focusable>
  );
}

function ManifestEditor({ initial, onClose, onSaved }: ManifestEditorProps) {
  const [settings, setSettings] = useState(initial);
  const [selectedDisc, setSelectedDisc] = useState(0);
  const initialDefaults = layoutDefaults[initial.preset] ?? layoutDefaults.list;
  const [gridOverride, setGridOverride] = useState(
    initial.columns !== initialDefaults.columns || initial.rows !== initialDefaults.rows,
  );
  const [saving, setSaving] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [animationPreviewing, setAnimationPreviewing] = useState(false);
  const dirty = JSON.stringify(settings) !== JSON.stringify(initial);
  const disc = settings.discs[selectedDisc];

  useEffect(() => () => { void stopMusicPreview(); }, []);
  useEffect(() => setAnimationPreviewing(false), [selectedDisc]);

  const updateDisc = (change: (current: DiscSettings) => DiscSettings) => {
    setSettings((current) => ({
      ...current,
      discs: current.discs.map((item, index) => index === selectedDisc ? change(item) : item),
    }));
  };

  const stopPreview = async () => {
    await stopMusicPreview();
    setPreviewing(false);
  };

  const chooseFile = async (kind: "image" | "music" | "disc" | "artwork") => {
    const current = kind === "image"
      ? settings.backgroundImage
      : kind === "music"
        ? settings.musicPath
        : kind === "disc"
          ? disc.path
          : disc.artwork;
    const extensions = kind === "image" || kind === "artwork"
      ? ["jpg", "jpeg", "png", "svg", "webp"]
      : kind === "music"
        ? ["flac", "m4a", "mp3", "ogg", "opus", "wav"]
        : undefined;
    try {
      const result = await openFilePicker(
        FileSelectionType.FILE,
        pickerStart(current.startsWith("/") ? current : settings.path),
        true,
        true,
        undefined,
        extensions,
        false,
        kind === "disc",
      );
      if (!result?.path) return;
      if (kind === "image") {
        setSettings((value) => ({ ...value, backgroundImage: result.path }));
      } else if (kind === "music") {
        await stopPreview();
        setSettings((value) => ({ ...value, musicPath: result.path }));
      } else if (kind === "disc") {
        updateDisc((value) => ({ ...value, path: result.path }));
      } else {
        updateDisc((value) => ({ ...value, artwork: result.path }));
      }
    } catch (error) {
      toaster.toast({ title: "File picker failed", body: String(error) });
    }
  };

  const togglePreview = async () => {
    if (previewing) {
      await stopPreview();
      return;
    }
    const result = await previewMusic(settings.path, settings.musicPath, settings.musicVolume);
    if (!result.ok) {
      toaster.toast({ title: "Music preview failed", body: result.error ?? "Unknown error" });
      return;
    }
    setPreviewing(true);
  };

  const requestClose = () => {
    if (!dirty) {
      void stopPreview();
      onClose();
      return;
    }
    showModal(
      <ConfirmModal
        strTitle="Discard unsaved changes?"
        strDescription="Your manifest has changes that have not been saved."
        strOKButtonText="Discard"
        strCancelButtonText="Keep editing"
        bDestructiveWarning
        onOK={() => { void stopPreview(); onClose(); }}
      />,
    );
  };

  const addDisc = () => {
    const next = settings.discs.length;
    setSettings((current) => ({ ...current, discs: [...current.discs, newDisc(next + 1)] }));
    setSelectedDisc(next);
  };

  const removeDisc = () => {
    if (settings.discs.length === 1) return;
    showModal(
      <ConfirmModal
        strTitle={`Remove ${disc.label}?`}
        strDescription="The disc will be removed when you save the manifest."
        strOKButtonText="Remove"
        bDestructiveWarning
        onOK={() => {
          setSettings((current) => ({
            ...current,
            discs: current.discs.filter((_item, index) => index !== selectedDisc),
          }));
          setSelectedDisc(Math.max(0, selectedDisc - 1));
        }}
      />,
    );
  };

  const moveDisc = (direction: -1 | 1) => {
    const destination = selectedDisc + direction;
    if (destination < 0 || destination >= settings.discs.length) return;
    setSettings((current) => {
      const discs = [...current.discs];
      [discs[selectedDisc], discs[destination]] = [discs[destination], discs[selectedDisc]];
      return { ...current, discs };
    });
    setSelectedDisc(destination);
  };

  const save = async () => {
    setSaving(true);
    try {
      const result = await updateManifestSettings(settings.path, settings);
      if (!result.ok || !result.settings) {
        toaster.toast({ title: "Manifest update failed", body: result.error ?? "Unknown backend error" });
        return;
      }
      toaster.toast({ title: `${settings.title} updated`, body: "Manifest settings saved" });
      await stopPreview();
      await onSaved();
      onClose();
    } catch (error) {
      toaster.toast({ title: "Manifest update failed", body: String(error) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <ModalRoot bAllowFullSize bDisableBackgroundDismiss closeModal={requestClose}>
      <div style={{ maxHeight: "72vh", overflowY: "auto", paddingRight: 12 }}>
        <PanelSection title="Layout">
          <PanelSectionRow>
            <SettingsGroup>
              <Field label="Preset" description="Selector presentation preset" childrenLayout="below">
                <Dropdown
                  rgOptions={layoutOptions}
                  selectedOption={settings.preset}
                  onChange={(option) => {
                    const preset = String(option.data);
                    setSettings((value) => ({ ...value, preset, ...layoutDefaults[preset] }));
                    setGridOverride(false);
                  }}
                />
              </Field>
              <ToggleField
                label="Custom grid override"
                description="Override the preset's standard rows and columns"
                checked={gridOverride}
                onChange={(enabled) => {
                  setGridOverride(enabled);
                  if (!enabled) setSettings((value) => ({ ...value, ...layoutDefaults[value.preset] }));
                }}
              />
              {gridOverride && <>
                <SliderField label="Columns" value={settings.columns} min={1} max={8} step={1} showValue onChange={(columns) => setSettings((value) => ({ ...value, columns }))} />
                <SliderField label="Rows" value={settings.rows} min={1} max={8} step={1} showValue onChange={(rows) => setSettings((value) => ({ ...value, rows }))} />
              </>}
            </SettingsGroup>
          </PanelSectionRow>
        </PanelSection>

        <PanelSection title="Background">
          <PanelSectionRow>
            <SettingsGroup>
              <ArtworkPicker
                manifestPath={settings.path}
                imagePath={settings.backgroundImage}
                wide
                dim={settings.backgroundDim}
                label="Background Artwork"
                onBrowse={() => void chooseFile("image")}
                onClear={() => setSettings((value) => ({ ...value, backgroundImage: "" }))}
              />
              <SliderField label="Dim" description="Black overlay strength" value={Math.round(settings.backgroundDim * 100)} min={0} max={100} step={5} showValue valueSuffix="%" onChange={(value) => setSettings((current) => ({ ...current, backgroundDim: value / 100 }))} />
            </SettingsGroup>
          </PanelSectionRow>
        </PanelSection>

        <PanelSection title="Music">
          <PanelSectionRow>
            <SettingsGroup>
              <ButtonItem layout="below" description={settings.musicPath || "No music selected"} onClick={() => void chooseFile("music")}><FaFolderOpen style={{ marginRight: 8 }} /> Select music</ButtonItem>
              {settings.musicPath && (
                <Focusable flow-children="right" style={{ display: "flex", gap: 8, width: "100%" }}>
                  <div style={{ flex: 1 }}><ModalActionButton onPress={() => void togglePreview()}>{previewing ? <><FaStop style={{ marginRight: 8 }} /> Stop preview</> : <><FaVolumeHigh style={{ marginRight: 8 }} /> Preview music</>}</ModalActionButton></div>
                  <div style={{ flex: 1 }}><ModalActionButton onPress={() => { void stopPreview(); setSettings((value) => ({ ...value, musicPath: "" })); }}><FaXmark style={{ marginRight: 8 }} /> Clear music</ModalActionButton></div>
                </Focusable>
              )}
              <SliderField label="Volume" value={Math.round(settings.musicVolume * 100)} min={0} max={100} step={5} showValue valueSuffix="%" onChange={(value) => setSettings((current) => ({ ...current, musicVolume: value / 100 }))} />
              <ToggleField label="Loop music" checked={settings.musicLoop} onChange={(musicLoop) => setSettings((value) => ({ ...value, musicLoop }))} />
            </SettingsGroup>
          </PanelSectionRow>
        </PanelSection>

        <PanelSection title={`Discs (${settings.discs.length})`}>
          <PanelSectionRow>
            <SettingsGroup>
              <Focusable flow-children="down" style={{ display: "flex", flexDirection: "column", gap: 8, width: "100%" }}>
                <div style={{ fontWeight: 600 }}>Select Disc</div>
                <Dropdown rgOptions={settings.discs.map((item, index) => ({ data: index, label: `${index + 1}. ${item.label}` }))} selectedOption={selectedDisc} onChange={(option) => setSelectedDisc(Number(option.data))} />
                <div style={{ textAlign: "center", opacity: 0.7 }}>or</div>
                <ModalActionButton onPress={addDisc}><FaPlus style={{ marginRight: 6 }} /> Add Disc</ModalActionButton>
              </Focusable>
              <TextField label="Label" value={disc.label} onChange={(event) => updateDisc((value) => ({ ...value, label: event.target.value }))} />
              <ButtonItem layout="below" description={disc.path || "No disc content selected"} onClick={() => void chooseFile("disc")}><FaFolderOpen style={{ marginRight: 8 }} /> Select ROM or disc image</ButtonItem>
              <ArtworkPicker
                manifestPath={settings.path}
                imagePath={disc.artwork}
                animation={disc.animation}
                previewing={animationPreviewing}
                label="Disc Artwork"
                onBrowse={() => void chooseFile("artwork")}
                onClear={() => { setAnimationPreviewing(false); updateDisc((value) => ({ ...value, artwork: "" })); }}
              />
              <ModalActionButton
                disabled={disc.animation.type === "none" || !disc.artwork}
                onPress={() => setAnimationPreviewing((value) => !value)}
              >
                {animationPreviewing
                  ? <><FaStop style={{ marginRight: 8 }} /> Stop Preview</>
                  : <><FaPlay style={{ marginRight: 8 }} /> Preview Animation</>}
              </ModalActionButton>
              <Field label="Animation" childrenLayout="below">
                <Dropdown rgOptions={animationOptions} selectedOption={disc.animation.type} onChange={(option) => { setAnimationPreviewing(false); updateDisc((value) => ({ ...value, animation: { ...value.animation, type: option.data as AnimationSettings["type"] } })); }} />
              </Field>
              {disc.animation.type !== "none" && <SliderField label="Start delay" value={disc.animation.delay} min={0} max={10} step={0.5} showValue valueSuffix="s" onChange={(delay) => updateDisc((value) => ({ ...value, animation: { ...value.animation, delay } }))} />}
              {disc.animation.type === "spin" && <SliderField label="Spin speed" value={disc.animation.revolutionsPerMinute} min={1} max={60} step={1} showValue valueSuffix=" RPM" onChange={(revolutionsPerMinute) => updateDisc((value) => ({ ...value, animation: { ...value.animation, revolutionsPerMinute } }))} />}
              {disc.animation.type === "wiggle" && <>
                <SliderField label="Wiggle angle" value={disc.animation.angle} min={0} max={90} step={1} showValue valueSuffix="°" onChange={(angle) => updateDisc((value) => ({ ...value, animation: { ...value.animation, angle } }))} />
                <SliderField label="Vertical movement" value={disc.animation.distance} min={0} max={50} step={1} showValue valueSuffix=" px" onChange={(distance) => updateDisc((value) => ({ ...value, animation: { ...value.animation, distance } }))} />
                <SliderField label="Wiggle period" value={disc.animation.period} min={0.1} max={5} step={0.1} showValue valueSuffix="s" onChange={(period) => updateDisc((value) => ({ ...value, animation: { ...value.animation, period } }))} />
              </>}
              <Focusable flow-children="right" style={{ display: "flex", flexDirection: "column", gap: 8, width: "100%" }}>
              <div style={{ fontWeight: 600 }}>Selected Disc Actions</div>
              <Focusable flow-children="right" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                <ModalActionButton disabled={selectedDisc === 0} onPress={() => moveDisc(-1)}><FaArrowUp style={{ marginRight: 6 }} /> Move Up</ModalActionButton>
                <ModalActionButton disabled={selectedDisc === settings.discs.length - 1} onPress={() => moveDisc(1)}><FaArrowDown style={{ marginRight: 6 }} /> Move Down</ModalActionButton>
                <ModalActionButton disabled={settings.discs.length === 1} onPress={removeDisc}><FaTrash style={{ marginRight: 6 }} /> Delete</ModalActionButton>
              </Focusable>
              </Focusable>
            </SettingsGroup>
          </PanelSectionRow>
        </PanelSection>

        <PanelSection title="Apply">
          <PanelSectionRow>
            <SettingsGroup>
              <ButtonItem disabled={saving || !dirty} onClick={() => void save()}>{saving ? <Spinner /> : <><FaFloppyDisk style={{ marginRight: 8 }} /> Save changes</>}</ButtonItem>
              <ButtonItem disabled={saving} onClick={requestClose}><FaXmark style={{ marginRight: 8 }} /> Cancel</ButtonItem>
            </SettingsGroup>
          </PanelSectionRow>
        </PanelSection>
      </div>
    </ModalRoot>
  );
}

function Content() {
  const [status, setStatus] = useState<RuntimeStatus | null>(null);
  const [scan, setScan] = useState<ScanResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [editorLoading, setEditorLoading] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [nextStatus, nextScan] = await Promise.all([
        getRuntimeStatus(),
        scanManifests(),
      ]);
      setStatus(nextStatus);
      setScan(nextScan);
    } catch (error) {
      toaster.toast({
        title: "DiscShelf refresh failed",
        body: String(error),
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const launch = async (manifest: ManifestSummary) => {
    Navigation.CloseSideMenus();
    await new Promise((resolve) => window.setTimeout(resolve, 350));
    const result = await launchManifest(manifest.path);
    if (result.ok) {
      toaster.toast({
        title: `Launching ${manifest.title}`,
        body: `${manifest.discCount} discs • ${manifest.layout}`,
      });
    } else {
      toaster.toast({
        title: "DiscShelf launch failed",
        body: result.error ?? "Unknown backend error",
      });
    }
  };

  const edit = async (manifest: ManifestSummary) => {
    setEditorLoading(manifest.path);
    try {
      const result = await getManifestSettings(manifest.path);
      if (!result.ok || !result.settings) {
        toaster.toast({
          title: "Could not edit manifest",
          body: result.error ?? "Unknown backend error",
        });
        return;
      }
      let modal: ReturnType<typeof showModal>;
      const close = () => modal.Close();
      modal = showModal(
        <ManifestEditor initial={result.settings} onClose={close} onSaved={refresh} />,
        undefined,
        {
          strTitle: `Edit ${result.settings.title}`,
          bHideActionIcons: true,
          bHideMainWindowForPopouts: false,
        },
      );
    } catch (error) {
      toaster.toast({ title: "Could not edit manifest", body: String(error) });
    } finally {
      setEditorLoading(null);
    }
  };

  return (
    <>
      <PanelSection title="Runtime">
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            description={
              status?.available
                ? `${status.version ?? "Unknown version"} • ${status.source} • ${status.path}`
                : status?.error ?? "DiscShelf runtime not found"
            }
            onClick={() => void refresh()}
          >
            {loading ? <Spinner /> : status?.available ? "Runtime ready" : "Runtime unavailable"}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title={`Manifests${scan ? ` (${scan.manifests.length})` : ""}`}>
        {loading && !scan ? (
          <PanelSectionRow><Spinner /></PanelSectionRow>
        ) : scan?.manifests.length ? (
          scan.manifests.map((manifest) => (
            <PanelSectionRow key={manifest.path}>
              <Field
                label={manifest.title}
                description={
                  manifest.valid
                    ? `${manifest.discCount} discs • ${manifest.layout}`
                    : manifest.error ?? "Invalid manifest"
                }
                childrenContainerWidth="min"
              >
                <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  <Button
                    style={{ width: 38, minWidth: 38, height: 40, padding: 0 }}
                    disabled={!manifest.valid || !status?.available}
                    onClick={() => void launch(manifest)}
                  >
                    <FaPlay />
                  </Button>
                  <Button
                    style={{ width: 92, minWidth: 92, height: 40, padding: "0 8px" }}
                    disabled={!manifest.valid || editorLoading === manifest.path}
                    onClick={() => void edit(manifest)}
                  >
                    {editorLoading === manifest.path ? (
                      <Spinner />
                    ) : (
                      <><FaPen style={{ marginRight: 8 }} /> Edit</>
                    )}
                  </Button>
                </div>
              </Field>
            </PanelSectionRow>
          ))
        ) : (
          <PanelSectionRow>No DiscShelf manifests found.</PanelSectionRow>
        )}
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => void refresh()}>
            <FaRotate style={{ marginRight: 8 }} /> Refresh
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

export default definePlugin(() => ({
  name: "DiscShelf",
  titleView: <div className={staticClasses.Title}>DiscShelf</div>,
  content: <Content />,
  icon: <FaCompactDisc />,
  onDismount() {},
}));
