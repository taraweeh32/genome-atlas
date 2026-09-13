import { SkeletonRows } from "@/components/ui/states";

/** Loading foundation for authenticated application routes. */
export default function ApplicationLoading() {
  return <SkeletonRows rows={5} />;
}
