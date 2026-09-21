"""Strict write contract; bind secrets are never part of a read projection."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
class DirectoryConfig(BaseModel):
    model_config=ConfigDict(extra='forbid')
    enabled: bool
    host: str=Field(min_length=1,max_length=253)
    port: int=Field(ge=1,le=65535,strict=True)
    bind_dn: str=Field(min_length=1,max_length=1024)
    user_base: str=Field(min_length=1,max_length=1024)
    group_base: str=Field(min_length=1,max_length=1024)
    user_attribute: str=Field(min_length=1,max_length=64)
    user_object_class: str=Field(min_length=1,max_length=64)
    group_object_class: str=Field(min_length=1,max_length=64)
    member_attribute: str=Field(min_length=1,max_length=64)
    identity_attribute: str=Field(min_length=1,max_length=64)
    account_control_attribute: str=Field(min_length=1,max_length=64)
    ca_pem: str=Field(max_length=8192)
    group_dn: str=Field(min_length=1,max_length=1024)
class DirectoryChange(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_revision: int=Field(ge=0,strict=True)
    config: DirectoryConfig
    bind_password: str=Field(default='',max_length=4096,repr=False)
