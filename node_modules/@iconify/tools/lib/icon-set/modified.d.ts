import { IconSet } from "./index.js";
/**
 * Check if icons in an icon set were updated.
 *
 * This function checks only icons, not metadata. It also ignores icon visibility.
 */
declare function hasIconDataBeenModified(set1: IconSet, set2: IconSet): boolean;
export { hasIconDataBeenModified };