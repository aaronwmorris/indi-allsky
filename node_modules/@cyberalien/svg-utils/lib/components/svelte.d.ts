import { FactoryIconData } from "./types/data.js";
import { ComponentFactoryOptions } from "./types/options.js";
import { FactoryGeneratedComponent } from "./types/component.js";
interface SvelteOptions extends ComponentFactoryOptions {
  ts?: boolean;
}
/**
 * Create Svelte component code
 */
declare function createSvelteComponent(data: FactoryIconData, options: SvelteOptions): FactoryGeneratedComponent;
export { createSvelteComponent };