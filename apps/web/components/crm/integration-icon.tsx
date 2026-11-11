import { Icon } from "./icon";
const marks: Record<string, string> = {
  hermes: "H",
  zernio: "Z",
  facebook: "f",
  instagram: "IG",
  tiktok: "Tk",
  whatsapp: "WA",
  telegram: "TG",
};
export function IntegrationIcon({ name }: { name: string }) {
  return (
    <span
      className={`settings-integration-icon integration-${name}`}
      aria-hidden="true"
    >
      {marks[name] ?? (
        <Icon
          name={
            name === "skill"
              ? "task"
              : name === "script"
                ? "list"
                : "connections"
          }
          size={20}
        />
      )}
    </span>
  );
}
export function SettingsSwitch({
  name,
  checked,
  disabled,
  onChange,
}: {
  name: string;
  checked: boolean;
  disabled?: boolean;
  onChange: () => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-label={name}
      aria-checked={checked}
      disabled={disabled}
      className="settings-switch"
      onClick={onChange}
    >
      <span />
    </button>
  );
}
