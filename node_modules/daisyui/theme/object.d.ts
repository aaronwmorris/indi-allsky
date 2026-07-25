interface Theme {
  "color-scheme": string
  "--color-base-100": string
  "--color-base-200": string
  "--color-base-300": string
  "--color-base-content": string
  "--color-primary": string
  "--color-primary-content": string
  "--color-secondary": string
  "--color-secondary-content": string
  "--color-accent": string
  "--color-accent-content": string
  "--color-neutral": string
  "--color-neutral-content": string
  "--color-info": string
  "--color-info-content": string
  "--color-success": string
  "--color-success-content": string
  "--color-warning": string
  "--color-warning-content": string
  "--color-error": string
  "--color-error-content": string
  "--radius-selector": string
  "--radius-field": string
  "--radius-box": string
  "--size-selector": string
  "--size-field": string
  "--border": string
  "--depth": string
  "--noise": string
}


interface Themes {
  winter: Theme
  silk: Theme
  night: Theme
  autumn: Theme
  forest: Theme
  nord: Theme
  cupcake: Theme
  lemonade: Theme
  business: Theme
  retro: Theme
  black: Theme
  garden: Theme
  abyss: Theme
  bumblebee: Theme
  corporate: Theme
  emerald: Theme
  coffee: Theme
  aqua: Theme
  wireframe: Theme
  light: Theme
  sunset: Theme
  halloween: Theme
  dracula: Theme
  lofi: Theme
  luxury: Theme
  cyberpunk: Theme
  caramellatte: Theme
  dark: Theme
  fantasy: Theme
  pastel: Theme
  acid: Theme
  cmyk: Theme
  valentine: Theme
  synthwave: Theme
  dim: Theme
  [key: string]: Theme
}

declare const themes: Themes
export default themes