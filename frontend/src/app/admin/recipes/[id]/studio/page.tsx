import { redirect } from "next/navigation";

// The studio is the only recipe editor and lives at /admin/recipes/[id]; this keeps old bookmarks working.
export default function RecipeStudioRedirect({ params }: { params: { id: string } }) {
  redirect(`/admin/recipes/${params.id}`);
}
