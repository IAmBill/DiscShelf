import {
  Button,
  ButtonItem,
  Dropdown,
  Field,
  ModalRoot,
  Navigation,
  PanelSection,
  PanelSectionRow,
  SliderField,
  Spinner,
  staticClasses,
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
import { useCallback, useEffect, useState } from "react";
import {
  FaCompactDisc,
  FaFloppyDisk,
  FaFolderOpen,
  FaPen,
  FaPlay,
  FaRotate,
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
};

type SettingsResult = {
  ok: boolean;
  settings: ManifestSettings | null;
  error: string | null;
};

const layoutOptions = [
  { data: "list", label: "List" },
  { data: "showcase", label: "Showcase" },
  { data: "strip", label: "Strip" },
  { data: "compact", label: "Compact" },
  { data: "wide-grid", label: "Wide grid" },
];

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

function ManifestEditor({ initial, onClose, onSaved }: ManifestEditorProps) {
  const [settings, setSettings] = useState(initial);
  const initialDefaults = layoutDefaults[initial.preset] ?? layoutDefaults.list;
  const [gridOverride, setGridOverride] = useState(
    initial.columns !== initialDefaults.columns || initial.rows !== initialDefaults.rows,
  );
  const [saving, setSaving] = useState(false);

  const chooseFile = async (kind: "image" | "music") => {
    const current = kind === "image" ? settings.backgroundImage : settings.musicPath;
    const extensions = kind === "image"
      ? ["jpg", "jpeg", "png", "svg", "webp"]
      : ["flac", "m4a", "mp3", "ogg", "opus", "wav"];
    try {
      const result = await openFilePicker(
        FileSelectionType.FILE,
        pickerStart(current.startsWith("/") ? current : settings.path),
        true,
        true,
        undefined,
        extensions,
        false,
        false,
      );
      if (result?.path) {
        setSettings((value) => ({
          ...value,
          [kind === "image" ? "backgroundImage" : "musicPath"]: result.path,
        }));
      }
    } catch (error) {
      toaster.toast({ title: "File picker failed", body: String(error) });
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      const result = await updateManifestSettings(settings.path, settings);
      if (!result.ok || !result.settings) {
        toaster.toast({
          title: "Manifest update failed",
          body: result.error ?? "Unknown backend error",
        });
        return;
      }
      toaster.toast({ title: `${settings.title} updated`, body: "Appearance settings saved" });
      await onSaved();
      onClose();
    } catch (error) {
      toaster.toast({ title: "Manifest update failed", body: String(error) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <ModalRoot
      bAllowFullSize
      bDisableBackgroundDismiss
      closeModal={onClose}
    >
      <div style={{ maxHeight: "72vh", overflowY: "auto", paddingRight: 12 }}>
      <PanelSection title={`Edit ${settings.title}`}>
      <PanelSectionRow>
        <Field label="Layout" description="Selector presentation preset" childrenLayout="below">
          <Dropdown
            rgOptions={layoutOptions}
            selectedOption={settings.preset}
            onChange={(option) => {
              const preset = String(option.data);
              const dimensions = layoutDefaults[preset];
              setSettings((value) => ({ ...value, preset, ...dimensions }));
              setGridOverride(false);
            }}
          />
        </Field>
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField
          label="Custom grid override"
          description="Override the selected preset's standard rows and columns"
          checked={gridOverride}
          onChange={(enabled) => {
            setGridOverride(enabled);
            if (!enabled) {
              const dimensions = layoutDefaults[settings.preset];
              setSettings((value) => ({ ...value, ...dimensions }));
            }
          }}
        />
      </PanelSectionRow>
      {gridOverride && (
        <>
          <PanelSectionRow>
            <SliderField
              label="Columns override"
              value={settings.columns}
              min={1}
              max={8}
              step={1}
              showValue
              onChange={(columns) => setSettings((value) => ({ ...value, columns }))}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <SliderField
              label="Rows override"
              value={settings.rows}
              min={1}
              max={8}
              step={1}
              showValue
              onChange={(rows) => setSettings((value) => ({ ...value, rows }))}
            />
          </PanelSectionRow>
        </>
      )}
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          description={settings.backgroundImage || "No background image selected"}
          onClick={() => void chooseFile("image")}
        >
          <FaFolderOpen style={{ marginRight: 8 }} /> Background image
        </ButtonItem>
      </PanelSectionRow>
      {settings.backgroundImage && (
        <PanelSectionRow>
          <ButtonItem
            onClick={() => setSettings((value) => ({ ...value, backgroundImage: "" }))}
          >
            <FaXmark style={{ marginRight: 8 }} /> Clear background image
          </ButtonItem>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <SliderField
          label="Background dim"
          description="Black overlay strength"
          value={Math.round(settings.backgroundDim * 100)}
          min={0}
          max={100}
          step={5}
          showValue
          valueSuffix="%"
          onChange={(value) => setSettings((current) => ({ ...current, backgroundDim: value / 100 }))}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          description={settings.musicPath || "No background music selected"}
          onClick={() => void chooseFile("music")}
        >
          <FaFolderOpen style={{ marginRight: 8 }} /> Background music
        </ButtonItem>
      </PanelSectionRow>
      {settings.musicPath && (
        <PanelSectionRow>
          <ButtonItem onClick={() => setSettings((value) => ({ ...value, musicPath: "" }))}>
            <FaXmark style={{ marginRight: 8 }} /> Clear background music
          </ButtonItem>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <SliderField
          label="Music volume"
          value={Math.round(settings.musicVolume * 100)}
          min={0}
          max={100}
          step={5}
          showValue
          valueSuffix="%"
          onChange={(value) => setSettings((current) => ({ ...current, musicVolume: value / 100 }))}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField
          label="Loop music"
          checked={settings.musicLoop}
          onChange={(musicLoop) => setSettings((value) => ({ ...value, musicLoop }))}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem disabled={saving} onClick={() => void save()}>
          {saving ? <Spinner /> : <><FaFloppyDisk style={{ marginRight: 8 }} /> Save changes</>}
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem disabled={saving} onClick={onClose}>
          <FaXmark style={{ marginRight: 8 }} /> Cancel
        </ButtonItem>
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
