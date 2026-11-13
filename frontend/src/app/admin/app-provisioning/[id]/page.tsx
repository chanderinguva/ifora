"use client";
import { useParams } from "next/navigation";
import { ProvisioningDetail } from "@/components/provisioning-detail";
export default function AppDetail() {
  const { id } = useParams<{ id: string }>();
  return <ProvisioningDetail id={id} />;
}

