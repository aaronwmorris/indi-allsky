import { IconifyJSON } from "@iconify/types";
/**
 * Get default properties from icon set
 */
declare function getIconifyIconSetDefaults(data: IconifyJSON): Partial<Record<"width" | "height" | "left" | "top", number>>;
export { getIconifyIconSetDefaults };