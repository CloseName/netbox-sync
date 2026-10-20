"""Ownership metadata cannot grant permissions or change synchronization identity."""
from copy import deepcopy
import pytest
from netbox_sync.auth_policy import AuthPolicy, AuthError
from tests.test_auth_policy import enrolled, call
from tests.test_directory_auth import configured, auth


def test_legacy_migration_cas_assignment_and_reopen():
    service,token,_=enrolled();before=deepcopy(service.state)
    assert 'source_teams' not in before
    data=call(service,token,'teams');assert data=={'version':1,'revision':0,'teams':{},'assignments':{}}
    data=call(service,token,'teams.create',revision=0,name='Compute QA')
    team=next(iter(data['teams']))
    with pytest.raises(AuthError,match='TEAM_CONFLICT'):call(service,token,'teams.create',revision=0,name='Other')
    data=call(service,token,'teams.assign',revision=1,team_id=team,source_instance='source-a')
    assert data['assignments']=={'source-a':team}
    data=call(service,token,'teams.rename',revision=2,team_id=team,name='Compute')
    assert data['assignments']=={'source-a':team}
    reopened=AuthPolicy(deepcopy(service.state),clock=lambda:1000)
    assert call(reopened,token,'teams')==data
    assert reopened.state['revision']==before['revision'] and reopened.state['principal']==before['principal']
    assert call(service,token,'teams.assign',revision=3,team_id=None,source_instance='source-a')['assignments']=={}
    assert [r['action'] for r in service.audit][-4:]==['teams.create','teams.assign','teams.rename','teams.assign']

@pytest.mark.parametrize('role',['viewer','operator','admin'])
def test_roles_never_derived_from_team(role):
    service,local,token=configured(role);before=auth(service,token)
    data=call(service,token,'teams');assert not data['assignments']
    if role!='admin':
        with pytest.raises(AuthError,match='AUTH_DENIED'):call(service,token,'teams.create',revision=0,name='admin')
    else:call(service,token,'teams.create',revision=0,name='viewer')
    assert auth(service,token)==before
    with pytest.raises(AuthError,match='AUTH_REQUIRED'):call(service,None,'teams')

def test_invalid_input_and_response_bound_leave_state_unchanged():
    service,token,_=enrolled();call(service,token,'teams');before=deepcopy(service.state['source_teams'])
    for values in ({'name':''},{'name':'x'*81},{'name':'line\nbreak'}):
        with pytest.raises(AuthError,match='TEAM_INVALID'):call(service,token,'teams.create',revision=0,**values)
    assert service.state['source_teams']==before


@pytest.mark.parametrize('team',[[],{},1,True])
def test_invalid_team_identifier_is_a_safe_validation_error(team):
    service,token,_=enrolled();before=deepcopy(service.state)
    with pytest.raises(AuthError,match='TEAM_INVALID'):
        call(service,token,'teams.assign',revision=0,team_id=team,source_instance='source-a')
    assert service.state==before


@pytest.mark.parametrize('revision', [True, False, '0', 0.0, None, -1])
def test_revision_refusal_precedes_invalid_team_and_name(revision):
    service, token, _ = enrolled()
    before = deepcopy(service.state)
    audit = deepcopy(service.audit)
    with pytest.raises(AuthError, match='^TEAM_CONFLICT$'):
        call(service, token, 'teams.create', revision=revision, team_id=[], name='')
    assert service.state == before
    assert service.audit == audit


def test_names_are_trimmed_unique_casefolded_and_response_is_detached():
    service, token, _ = enrolled()
    data = call(service, token, 'teams.create', revision=0, name='  Straße  ')
    team = next(iter(data['teams']))
    assert data['teams'][team]['name'] == 'Straße'
    data['teams'][team]['name'] = 'external mutation'
    assert service.state['source_teams']['teams'][team]['name'] == 'Straße'
    before = deepcopy(service.state['source_teams'])
    audit = deepcopy(service.audit)
    with pytest.raises(AuthError, match='^TEAM_INVALID$'):
        call(service, token, 'teams.create', revision=1, name='STRASSE')
    assert service.state['source_teams'] == before
    assert service.audit == audit
    data = call(service, token, 'teams.rename', revision=1, team_id=team, name='STRASSE')
    assert data['revision'] == 2 and data['teams'][team]['name'] == 'STRASSE'


def test_team_limit_blocks_creation_but_not_rename():
    service, token, _ = enrolled()
    service.state['source_teams'] = {'version': 1, 'revision': 0, 'assignments': {},
        'teams': {str(i): {'id': str(i), 'name': f'team-{i}'} for i in range(100)}}
    before = deepcopy(service.state['source_teams'])
    audit = deepcopy(service.audit)
    with pytest.raises(AuthError, match='^TEAM_INVALID$'):
        call(service, token, 'teams.create', revision=0, name='overflow')
    assert service.state['source_teams'] == before
    assert service.audit == audit
    data = call(service, token, 'teams.rename', revision=0, team_id='0', name='renamed')
    assert len(data['teams']) == 100 and data['revision'] == 1


def test_response_size_limit_precedes_commit_and_audit():
    service, token, _ = enrolled()
    service.state['source_teams'] = {'version': 1, 'revision': 0, 'teams': {},
        'assignments': {f'source-{i}': 'x' * 80 for i in range(300)}}
    before = deepcopy(service.state['source_teams'])
    audit = deepcopy(service.audit)
    with pytest.raises(AuthError, match='^TEAM_INVALID$'):
        call(service, token, 'teams.create', revision=0, name='valid')
    assert service.state['source_teams'] == before
    assert service.audit == audit


def test_unassign_missing_source_still_increments_revision_and_audits():
    service, token, _ = enrolled()
    data = call(service, token, 'teams.assign', revision=0, team_id=None, source_instance='source-a')
    assert data == {'version': 1, 'revision': 1, 'teams': {}, 'assignments': {}}
    assert service.audit[-1]['action'] == 'teams.assign'
