"""Read-only Compose hashing of the fully resolved model, kept in memory."""
import re
import subprocess


def resolved_hashes(directory, project, document):
    """Let Compose decode its own dollar escaping; never use terminal stdin.

    Direct config --hash leaves service env files unresolved in Compose 5.3.1.
    Render config first, then hash that complete model with the same Compose.
    No secret file, shell interpolation, daemon mutation or raw output logging.
    """
    result = subprocess.run(
        ['docker', 'compose', '--project-directory', str(directory), '-p', project,
         '-f', '-', 'config', '--hash', '*'],
        input=document, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=True, timeout=90,
    )
    hashes = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if (len(parts) != 2 or not re.fullmatch(r'[a-zA-Z0-9_.-]+', parts[0])
                or not re.fullmatch(r'[0-9a-f]{64}', parts[1]) or parts[0] in hashes):
            raise ValueError('Invalid Compose hash output')
        hashes[parts[0]] = parts[1]
    if not hashes:
        raise ValueError('Invalid Compose hash output')
    return hashes
