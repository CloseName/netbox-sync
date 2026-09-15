"""Narrow explicit catalog creation input; the temporary token is always masked."""
from uuid import UUID
from pydantic import BaseModel,ConfigDict,Field,SecretStr,StrictBool

class CatalogCreateDTO(BaseModel):
    model_config=ConfigDict(extra='forbid')
    operation_id:UUID
    object:dict
    write_token:SecretStr=Field(min_length=8,max_length=4096)
    confirm:StrictBool
