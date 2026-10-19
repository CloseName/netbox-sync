"""Source schedule endpoint registration with the existing schedule service."""
from .dto import ScheduleDTO, ScheduleUpdateDTO


def install_schedule_routes(router, *, schedule_service):
    """Keep schedule validation and persistence in the injected service."""
    @router.get('/sources/{source_instance}/schedule', response_model=ScheduleDTO)
    def source_schedule(source_instance: str):
        return ScheduleDTO.from_view(schedule_service.get(source_instance))

    @router.patch('/sources/{source_instance}/schedule', response_model=ScheduleDTO)
    def update_source_schedule(source_instance: str, payload: ScheduleUpdateDTO):
        return ScheduleDTO.from_view(schedule_service.update(
            source_instance, payload.model_dump()))
