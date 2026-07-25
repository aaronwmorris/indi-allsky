import { IconStatesList } from "../types.js";
import { StatefulIconSelectorsConfig, StatefulIconSelectorsContext } from "./types.js";
/**
 * Create context object from config
 */
declare function createStatefulIconSelectorsContext(config: StatefulIconSelectorsConfig, states: IconStatesList, staticClassname?: string): StatefulIconSelectorsContext;
/**
 * Get selectors to render state values
 *
 * Does not include shape class name
 */
declare function getSelectorsForStateValues(context: StatefulIconSelectorsContext, value: string | Record<string, string | boolean>): string[][] | null;
export { createStatefulIconSelectorsContext, getSelectorsForStateValues };