import {
  ButtonItem,
  Navigation,
  PanelSection,
  PanelSectionRow,
  Spinner,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin, toaster } from "@decky/api";
import { useCallback, useEffect, useState } from "react";
import { FaCompactDisc, FaPlay, FaRotate } from "react-icons/fa6";

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

const getRuntimeStatus = callable<[], RuntimeStatus>("get_runtime_status");
const scanManifests = callable<[], ScanResult>("scan_manifests");
const launchManifest = callable<[path: string], LaunchResult>("launch_manifest");

function Content() {
  const [status, setStatus] = useState<RuntimeStatus | null>(null);
  const [scan, setScan] = useState<ScanResult | null>(null);
  const [loading, setLoading] = useState(true);

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
              <ButtonItem
                layout="below"
                description={
                  manifest.valid
                    ? `${manifest.discCount} discs • ${manifest.layout}`
                    : manifest.error ?? "Invalid manifest"
                }
                disabled={!manifest.valid || !status?.available}
                onClick={() => void launch(manifest)}
              >
                <FaPlay style={{ marginRight: 8 }} />
                {manifest.title}
              </ButtonItem>
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
