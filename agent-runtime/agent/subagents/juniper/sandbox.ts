import { defineSandbox } from 'eve/sandbox';
import { JustBashSandbox } from 'eve/sandbox/just-bash';

// These API-only agents expose no shell or filesystem tools. Keep an explicit
// virtual filesystem so local builds never select a VM or cloud provider.
export const environment = JustBashSandbox.environment({ autoInstall: false });
export default defineSandbox(() => environment.open());
