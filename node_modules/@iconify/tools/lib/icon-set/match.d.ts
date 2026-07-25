import { IconSet } from "./index.js";
import { FullIconifyIcon } from "@iconify/utils/lib/icon/defaults";
/**
 * Find matching icon in icon set
 */
declare function findMatchingIcon(iconSet: IconSet, icon: FullIconifyIcon): string | null;
export { findMatchingIcon };