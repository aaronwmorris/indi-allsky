import { IconFallbackTemplate } from "./types.js";
/**
 * Generate fallback string from template and states
 */
declare function getIconFallback(template: IconFallbackTemplate, values: Record<string, boolean | string>, defaultValues?: Record<string, boolean | string>): string;
export { getIconFallback };