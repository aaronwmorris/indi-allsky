import { addComponentTypes } from "./wrapper.js";
/**
* Add Svelte component types
*/
const addSvelteComponentTypes = addComponentTypes.bind(null, `import { SvelteComponent } from "svelte";
import { SvelteHTMLElements } from "svelte/elements";

interface IconProps {
/* PROPS */
}

declare class Component extends SvelteComponent<Omit<SvelteHTMLElements['svg'], 'viewBox' | 'width' | 'height' | 'xmlns'> & IconProps & Record<\`data-\${string}\`, string>> {}

export { type IconProps };
export default Component;
`);
export { addSvelteComponentTypes };
