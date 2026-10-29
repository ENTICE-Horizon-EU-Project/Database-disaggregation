import pytest
from openpyxl import Workbook
from database_disaggregation import SplitPlan


def workbook(path,steps):
    b=Workbook();s=b.active;s.title='Master';s.append(['Sector','Parent Sector']);s.append(['p','P']);s.append(['q','P']);s.append(['p','P'])
    s=b.create_sheet('Intermediate steps')
    for row in steps:s.append(row)
    b.save(path)


def test_plan_reads_metadata_and_partitions_without_loading_mario(tmp_path):
    p=tmp_path/'input.xlsx';workbook(p,[['First','Second'],['p','q']]);plan=SplitPlan.read(p)
    assert plan.sectors==('p','q') and plan.steps=={'First':['p'],'Second':['q']}


@pytest.mark.parametrize('steps',[[['First','Second'],['p','p']],[['First'],['p']],[['First'],['missing']]])
def test_plan_rejects_missing_duplicate_or_unknown_sector(tmp_path,steps):
    p=tmp_path/'bad.xlsx';workbook(p,steps)
    with pytest.raises(ValueError):SplitPlan.read(p)
