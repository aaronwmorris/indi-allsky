import { IconStatesList } from "../types.js";
/**
 * Sub-parts of selector
 */
interface StateSelectorSubParts {
  tag?: string;
  id?: string;
  combinator?: string;
  name?: Set<string>;
  attr?: Set<string>;
  pseudo?: Set<string>;
}
/**
 * Parts of selector
 */
interface StateSelectorParts {
  at?: string[];
  parents?: StateSelectorSubParts[];
  svg?: StateSelectorSubParts;
}
type StateSelectorData = StateSelectorParts[][];
/**
 * Class names config
 */
type StatefulIconSelectorsConfig = Record<string, string | StateSelectorData | Record<string, string | StateSelectorData>>;
/**
 * Data for generating selectors for states
 *
 * Includes config and cache
 */
interface StatefulIconSelectorsContext {
  config: StatefulIconSelectorsConfig;
  states: IconStatesList;
  staticClassname?: string;
  data: Record<string, StateSelectorData | null>;
  parsed: Record<string, string[][] | null>;
}
export { StateSelectorData, StateSelectorParts, StateSelectorSubParts, StatefulIconSelectorsConfig, StatefulIconSelectorsContext };