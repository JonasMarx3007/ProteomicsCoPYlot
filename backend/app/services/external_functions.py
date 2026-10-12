# SPDX-License-Identifier: GPL-3.0-only
# Original R implementation: Alexander Hogrebe, Perseus Plugin Peptide Collapse.
# Python translation/rewrite: Denys Oliinyk and Yue Yang.
# See NOTICE for attribution.
import time
import warnings
import numpy as np
import itertools
import re
import os
import pandas as pd

def peptideCollapse(data, cutoff=0.0, collapse_level='PG', *, progress=None):
    """Collapse Spectronaut phosphosites, removing missing sentinels before log2.

    cutoff defaults to 0 (all sites); use 0.75 for Class I sites.
    collapse_level selects protein groups ('PG') or proteins ('P').
    """
    emit = print if progress is None else progress
    st = time.time()
    emit('Preliminary check of dataset:')
    # Preliminary check of dataset columns. If some of the columns are absent, exit the function
    must_have = list(['R.FileName', 'EG.PrecursorId',
                      'EG.TotalQuantity (Settings)',
                      'PEP.PeptidePosition',
                      'EG.PTMAssayProbability',
                      'PG.Genes',
                      'PG.ProteinGroups'])
    for exp in must_have:
        if exp in list(data.columns):
            emit(exp + ' ' + 'is in columns')
        else:
            emit(exp + ' ' + 'is not in columns:' + ' ' + 'please, provide' + ' ' + exp + ' ' + 'column')
            raise ValueError('Collapse stopped due to the absence of needed columns')
    ###################
    # Getting some preliminary functions
    regex_list = np.array(["^(.*)\\..$", "\\[[^[]*\\]", '_'])
    to_substitute = np.array(['\\1', '', ''])
    pat_del_all = "\\[(?!Phospho \\(STY\\))[^[]*\\]"
    keep = ['PEP.PeptidePosition', 'PG.ProteinGroups', 'PG.Genes', "PTM_0_num", "PTM_0_aa"]
    protgen = ['PG.Genes', 'PG.ProteinGroups', 'UPD_seq']
    fine_names = list(data['R.FileName'].unique())

    def fun(x):
        tempo = [len(line) for line in x.split('[Phospho (STY)]')]
        tmp = list(filter(None, [1, list(itertools.repeat(0, len(tempo) - 2)), 1]))
        output = []

        def unlist(l):
            for i in l:
                if type(i) == list:
                    unlist(i)
                else:
                    output.append(i)
            return (output)

        x = unlist(tmp)
        res = (np.cumsum((np.array(tempo) - np.array(x)).tolist()[:-1])).tolist()
        return (res)

    def fun1(col, start):
        res = col[start - 1:start]
        return (res)

    def fun2(x):
        if x >= 3:
            x = 3
        else:
            x = x
        return (x)

    def safe_text(value):
        if pd.isna(value):
            return ''
        return str(value).strip()

    def fun3(entry0, entry1, entry2, entry3, entry4, entry5):
        res = safe_text(entry0) + '~' + safe_text(entry1) + '_' + safe_text(entry2) + str((entry3 + entry4 - 1)) + '_M' + str(entry5)
        return (res)

    def fun4(entry1, entry2):
        res = entry1[:entry2 - 1] + entry1[entry2 - 1].lower() + '*' + entry1[entry2:]
        return (res)

    ##################
    emit('Start of dataset preprocessing:' + ' ' + 'dataset consists of' + ' ' + str(
        data.shape[0]) + ' ' + 'ID rows in' + ' ' + str(len(list(data['R.FileName'].unique()))) + ' ' + 'samples')
    # identifying the number of modifications per sequence
    data['PTM_0_num'] = data['EG.PrecursorId'].apply(lambda row: len(row.split('[Phospho (STY)]')) - 1)
    data['PTM_base_seq'] = data['EG.PrecursorId'].apply(lambda row: re.sub(regex_list[0], to_substitute[0], row))
    data['PTM_0_seq'] = data['PTM_base_seq']
    data['PTM_base_seq'] = data['PTM_base_seq'].apply(lambda row: re.sub(regex_list[1], to_substitute[1], row))
    data['PTM_base_seq'] = data['PTM_base_seq'].apply(lambda row: re.sub(regex_list[2], to_substitute[2], row))
    data['PTM_0_seq'] = data['PTM_0_seq'].apply(lambda row: re.sub(pat_del_all, '', row))
    num1 = data.shape[0]
    data = data[data['PTM_0_num'] > 0]
    num2 = num1 - data.shape[0]
    data['PTM_0_pos_val'] = data['PTM_0_seq'].apply(lambda row: fun(row))
    data['PTM_group'] = data['EG.PrecursorId']
    data = data.drop('PTM_0_seq', axis=1).explode('PTM_0_pos_val')
    data['UPD_seq'] = data.apply(lambda x: fun4(x['PTM_base_seq'], x['PTM_0_pos_val']), axis=1)
    data = data.reset_index()
    data['PTM_0_aa'] = data.apply(lambda x: fun1(x['PTM_base_seq'], x['PTM_0_pos_val']), axis=1)
    data = data.set_index('index')
    data['PTM_localization'] = data['EG.PTMAssayProbability'].astype(np.float64)
    txt_names = list(data.columns)
    txt_names.remove('EG.TotalQuantity (Settings)')
    emit('Preprocessing of dataset is done;' + ' ' + str(num2) + ' ' + 'nonphosphorylated IDs were removed')
    ####################
    df2 = pd.pivot_table(data, index=['PTM_group', 'PTM_0_pos_val'],
                         columns=['R.FileName'],
                         values=['EG.TotalQuantity (Settings)'],
                         aggfunc='first')
    df2 = df2.reindex(columns=pd.MultiIndex.from_product(
        [['EG.TotalQuantity (Settings)'], fine_names], names=df2.columns.names))
    # Spectronaut writes 0 and the string 'Filtered' for a measurement it did not
    # make. Both have to go before the transform: log2(0) is -inf, which notna()
    # counts as an observation, and a genuine intensity of 1 becomes log2 0, which
    # a replace(0, nan) after the transform would delete as if it were a sentinel.
    df2 = df2.apply(pd.to_numeric, errors='coerce')
    df2 = df2.replace(0, np.nan)
    df2 = np.log2(df2)
    # A run without a single phosphorylated precursor keeps its (empty) column,
    # so it stays visible beside its metadata; upstream (v20260728) drops it.
    empty_runs = [run for run in fine_names if df2[('EG.TotalQuantity (Settings)', run)].isna().all()]
    if empty_runs:
        emit('Notice: ' + str(len(empty_runs)) + ' run(s) have no measured phosphorylated precursor and stay empty: '
             + ', '.join(empty_runs))
    df3 = pd.pivot_table(data, index=['PTM_group', 'PTM_0_pos_val'],
                         columns=['R.FileName'],
                         values=['PTM_localization'],
                         aggfunc='first')
    df3 = df3.fillna(-1) # @Yue Yang: replace NaN with 0
    df3 = pd.DataFrame({'PTM_localization': df3.apply(max, axis=1)})
    df4 = pd.pivot_table(data, index=['PTM_group', 'PTM_0_pos_val'],
                         values=keep, aggfunc='first')
    df5 = pd.pivot_table(data, index=['PTM_group', 'PTM_0_pos_val'],
                         values=['UPD_seq'], aggfunc='first')
    data = pd.concat([df2, df4, df3, df5], axis=1).reset_index()
    emit('Long-to-wide formatting done')
    ####################
    class CustomWarning(Warning): # update @Yue Yang
     pass
    data['PG.Genes'] = data['PG.Genes'].apply(safe_text)
    data['PG.ProteinGroups'] = data['PG.ProteinGroups'].apply(safe_text)
    underscore_count = data['PG.Genes'].str.contains('_', na=False).sum()
    if underscore_count > 0:  # update @Yue Yang
     data['PG.Genes'] = data['PG.Genes'].str.replace('_', '#', regex=False)
     message = f"{underscore_count} gene names contained underscores and have been replaced with '#'."
     if progress is None:
      warnings.warn(message, CustomWarning)
     else:
      emit(message)
    else:
     emit("No gene names contained underscores.")
    data['PTM_Genprot'] = data['PG.Genes']
    num3 = data.shape[0] # update @Yue Yang
    data['PTM_pep_pos'] = data['PEP.PeptidePosition'].astype(str).apply(
        lambda row: list(filter(None, row.split(';')))[0])
    data['PTM_pep_pos'] = data['PTM_pep_pos'].astype(str).apply(lambda row: list(filter(None, row.split(',')))[0])
    data = data[
        (data['PTM_pep_pos'] != 'None') &
        (data['PG.Genes'] != '') &
        (data['PG.ProteinGroups'] != '') &
        (data['PTM_0_aa'].apply(safe_text) != '')
    ]
    data['PTM_pep_pos'] = data['PTM_pep_pos'].astype(np.int64)
    data['PTM_mult123'] = data['PTM_0_num'].astype(np.int64)
    data['PTM_mult123'] = data['PTM_mult123'].apply(lambda row: fun2(row))
    data['PTM_Collapse_key'] = data.apply(
        lambda x: fun3(x['PG.ProteinGroups'], x['PTM_Genprot'], x['PTM_0_aa'], x['PTM_0_pos_val'],
                       x['PTM_pep_pos'], x['PTM_mult123']), axis=1)
    num4 = num3 - data.shape[0] # update @Yue Yang
    emit('Preparation for collapsing done;' + ' ' + str(
        num4) + ' ' + 'phosphopeptides filtered due to insufficient information') # update @Yue Yang
    #################
    cols = [('EG.TotalQuantity (Settings)', run) for run in fine_names]

    # One row per site: a site's value in a run is the median of the log2
    # intensities of the precursors carrying it in that run -- a Perseus-style
    # choice that depends on which precursors each run measured. Its
    # localization is the maximum over runs and precursors, and the cutoff
    # below is applied to that maximum. Both are stated on the page.
    df1 = data.set_index('PTM_Collapse_key')
    df2 = df1[df1.columns[df1.columns.isin(cols)]]
    df2 = df2.reset_index()
    df3 = df2.groupby('PTM_Collapse_key').median()
    df4 = df1[df1.columns[df1.columns == 'PTM_localization']]
    df4 = df4.reset_index()
    df5 = df4.groupby('PTM_Collapse_key').max()
    df6 = df1[df1.columns[df1.columns.isin(protgen)]]
    df6 = df6.reset_index()
    df7 = df6.groupby('PTM_Collapse_key').first()
    data = pd.concat([df3, df7, df5], axis=1).reset_index()
    data['PTM_localization'] = data['PTM_localization'].replace(-1, np.nan) # @Yue Yang
    data = data[data['PTM_localization'] >= cutoff]
    # data = data.drop('PTM_localization', axis = 1)
    cols = []
    for c in list(data.columns):
        if type(c) == tuple:
            cols.append(c[1])
        else:
            cols.append(c)
    data.columns = cols
    if collapse_level == 'P':
        data['Protein_name'] = data['PTM_Collapse_key'].apply(lambda row: list(row.split('~'))[0])
        data['Protein_group'] = data['Protein_name'].str.split(';')
        data['Protein_group'] = data['Protein_group'].apply(lambda row: list(row)[0])
        data['Protein_name'] = data['Protein_name'].str.split(';')
        data['PTM'] = data['PTM_Collapse_key'].apply(lambda row: list(row.split('~'))[1])
        data[['Gene_name', 'Site', 'Mult']] = data['PTM'].str.split('_', expand=True)
        data['Gene_name'] = data['Gene_name'].str.split(';')
        data['Gene_group'] = data['Gene_name'].apply(lambda row: list(row)[0])
        data = data.drop(['Gene_name', 'PTM', 'PTM_Collapse_key', 'PG.Genes', 'PG.ProteinGroups'], axis=1)
        data = data.explode('Protein_name', ignore_index=True)
        data['PTM_Collapse_key'] = data['Protein_group'] + '~' + data['Gene_group'] + '_' + data['Site'] + '_' + data[
            'Mult']
        data['Protein_Collapse_key'] = data['Protein_name'] + '~' + data['Gene_group'] + '_' + data['Site'] + '_' + \
                                       data['Mult']
        data = data.drop(['Site', 'Mult'], axis=1)
        data['PTM_Collapse_key'] = data['PTM_Collapse_key'].str.replace('#', '_', regex=False) # Update @Yue Yang
        data['Gene_group'] = data['Gene_group'].str.replace('#', '_', regex=False) # Update @Yue Yang
        data, dropped = _finish_collapsed(data, fine_names)
        if dropped:
            emit(str(dropped) + ' site(s) without a value in any run were removed')
        emit('Collapse done succesfully;' + ' ' + str(data.shape[0]) + ' ' + 'unique phosphosite profiles')
        emit('Site values are the median of the log2 precursor intensities per run; '
             'localization is the maximum over runs and precursors, cutoff ' + str(cutoff))
        et = time.time()
        emit('Function executed in' + ' ' + str(round((et - st), 2)) + ' ' + 'seconds')
        return (data)
    if collapse_level == 'PG':
        data['Protein_name'] = data['PTM_Collapse_key'].apply(lambda row: list(row.split('~'))[0])
        data['Protein_group'] = data['Protein_name'].str.split(';')
        data['Protein_group'] = data['Protein_group'].apply(lambda row: list(row)[0])
        data['PTM'] = data['PTM_Collapse_key'].apply(lambda row: list(row.split('~'))[1])
        data[['Gene_name', 'Site', 'Mult']] = data['PTM'].str.split('_', expand=True)
        data['Gene_name'] = data['Gene_name'].str.split(';')
        data['Gene_group'] = data['Gene_name'].apply(lambda row: list(row)[0])
        data = data.drop(['Gene_name', 'Protein_name', 'PTM', 'PTM_Collapse_key', 'PG.Genes', 'PG.ProteinGroups'],
                         axis=1)
        data['PTM_Collapse_key'] = data['Protein_group'] + '~' + data['Gene_group'] + '_' + data['Site'] + '_' + data[
            'Mult']
        data = data.drop(['Site', 'Mult'], axis=1)
        data['PTM_Collapse_key'] = data['PTM_Collapse_key'].str.replace('#', '_', regex=False) # Update @Yue Yang
        data['Gene_group'] = data['Gene_group'].str.replace('#', '_', regex=False) # Update @Yue Yang
        data, dropped = _finish_collapsed(data, fine_names)
        if dropped:
            emit(str(dropped) + ' site(s) without a value in any run were removed')
        emit('Collapse done succesfully;' + ' ' + str(data.shape[0]) + ' ' + 'unique phosphosite profiles')
        emit('Site values are the median of the log2 precursor intensities per run; '
             'localization is the maximum over runs and precursors, cutoff ' + str(cutoff))
        et = time.time()
        emit('Function executed in' + ' ' + str(round((et - st), 2)) + ' ' + 'seconds')
        return (data)


def _finish_collapsed(data, fine_names):
    """Upstream v20260824's tidy-up: 'None' labels become missing, and a site
    without a value in any run is dropped (it carries no measurement)."""
    for column in ('Gene_group', 'Protein_group'):
        data[column] = data[column].replace('None', pd.NA)
    for column in ('PTM_Collapse_key', 'Protein_Collapse_key'):
        if column in data.columns:
            data[column] = data[column].str.replace(
                r'(^|~)None(?=~|_[^_]+_M\d+$)', r'\1 ', regex=True)
    runs = [run for run in fine_names if run in data.columns]
    before = data.shape[0]
    data = data.dropna(subset=runs, how='all')
    return data, before - data.shape[0]


def process_and_export(file_path, output_path=None, cutoff=0, *, progress=None):
    emit = print if progress is None else progress
    file_path = file_path.strip('"')
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"The file '{file_path}' does not exist.")
    emit(f"Reading file: {file_path}")
    data = pd.read_csv(file_path, sep='\t')
    emit("Applying peptide collapse ...")
    collapsed_data = peptideCollapse(data, cutoff=cutoff, progress=progress)
    if output_path is None:
        base_name, _ = os.path.splitext(file_path)
        output_path = f"{base_name}_collapsed.tsv"
    emit(f"Exporting collapsed data to: {output_path}")
    collapsed_data.to_csv(output_path, index=False, sep='\t')
    emit("File processed and exported successfully.")
    return collapsed_data
