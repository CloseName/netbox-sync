/** A shared, monochrome family: providers are identified by shape and text, not color. */
export function ProviderIcon({provider}: {provider: string}) {
  const paths: Record<string, string> = {
    esxi: 'M4 3h16v7H4z M4 14h16v7H4z M7 6h2 M7 17h2 M15 6h2 M15 17h2',
    proxmox: 'M12 2 3 7v10l9 5 9-5V7z M3 7l9 5 9-5 M12 12v10',
    pfsense: 'M12 2 4 5v6c0 5 4 9 8 11 4-2 8-6 8-11V5z M8 12l3 3 5-6',
    selectel: 'M6 18a5 5 0 0 1-1-10 7 7 0 0 1 13-1 5.5 5.5 0 0 1 0 11H6',
  };
  return <svg className="provider-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><path d={paths[provider]}/></svg>;
}
