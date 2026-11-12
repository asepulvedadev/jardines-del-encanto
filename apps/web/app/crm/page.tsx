import { redirect } from "next/navigation";
import { crmSession, crmWorkspace } from "../../lib/crm-server";
import { Workspace } from "../../components/crm/workspace";
import "./crm.css";
import "./retell.css";
import "./voice-workspace.css";

export const dynamic = "force-dynamic";
export const metadata = {
  title: "CRM | Jardines del Encanto",
  robots: { index: false, follow: false },
};

export default async function CrmPage() {
  const session = await crmSession();
  if (!session) redirect("/login");
  const data = await crmWorkspace();
  return (
    <Workspace
      initialData={data}
      user={session.user}
      csrf={session.csrf_token}
    />
  );
}
