/** Local assets: no third-party requests in the application. */
export function ProviderIcon({provider}: {provider: string}) {
 const files: Record<string,string> = {esxi:'esxi.svg',proxmox:'proxmox.svg',pfsense:'pfsense.svg',selectel:'selectel.png'};
 return files[provider] ? <img className="provider-icon" src={'/assets/providers/'+files[provider]} width={26} height={26} alt="" aria-hidden="true"/> : null;
}
